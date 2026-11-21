"""Phase 2: connect channels, encrypted tokens, channel settings, token health."""
import json
from html import escape
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import tokens as token_service
from app.services import youtube
from app.services.crypto import TokenCipher
from tests.conftest import FERNET_KEY, OWNER, sign_in

YT = youtube.YOUTUBE_SCOPE
ACCOUNT_SCOPE = "openid https://www.googleapis.com/auth/userinfo.email " + " ".join(youtube.ACCOUNT_SCOPES)
EXPECTED = [  # from config.yaml
    ("UC_ink", "Ink & Motion", "@inkandmotionyt"),
    ("UC_mirror", "Mirrorkin Press", "@mirrorkinpress"),
    ("UC_kidz", "Kidz Curious Labs", "@kidzcuriouslabs"),
    ("UC_ai", "AIPraveen", "@aipraveen18"),
]


@pytest.fixture
def owner(client, google):
    sign_in(client, google, OWNER)
    return client


@pytest.fixture
def yt_channel(monkeypatch):
    """Set .info to the channel YouTube reports for the next connect."""

    class Box:
        info = None
        calls: list = []

    box = Box()

    def fetch(access_token):
        box.calls.append(access_token)
        return box.info

    monkeypatch.setattr(youtube, "fetch_my_channel", fetch)
    return box


def csrf(client) -> str:
    text = client.get("/channels").text
    marker = 'name="csrf-token" content="'
    i = text.index(marker) + len(marker)
    return text[i:text.index('"', i)]


def connect(client, google, yt_channel, cid, title, handle, *, scope=YT, refresh="1//refresh-" , follow=True):
    start = client.get("/auth/channel/start", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    yt_channel.info = {"id": cid, "title": title, "handle": handle, "thumbnail_url": ""}
    google.token_response = {"scope": scope, **({"refresh_token": refresh + cid} if refresh else {})}
    return client.get(f"/auth/callback?code=c&state={q['state'][0]}", follow_redirects=follow)


# --- connect -----------------------------------------------------------------

def test_channel_connect_asks_google_for_offline_youtube_access(owner):
    r = owner.get("/auth/channel/start", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == [YT]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["select_account consent"]


def test_connect_requires_sign_in(client):
    r = client.get("/auth/channel/start", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_all_four_channels_connect_and_list_with_handles(owner, google, yt_channel, repo):
    for cid, title, handle in EXPECTED:
        page = connect(owner, google, yt_channel, cid, title, handle)
        assert f"Connected {escape(title)}" in page.text
    page = owner.get("/channels").text
    for _cid, title, handle in EXPECTED:
        assert escape(title) in page and handle in page
    assert page.count("● Connected") == 4
    assert "Not connected" in page  # the Sheets+Gmail account isn't connected yet
    assert len(repo.list_channels()) == 4
    assert "4<span" in owner.get("/").text  # dashboard: 4 / 4 connected


def test_connected_channel_gets_seed_defaults_from_config(owner, google, yt_channel, repo):
    connect(owner, google, yt_channel, "UC_mirror", "Mirrorkin Press", "@mirrorkinpress")
    ch = repo.get_channel("UC_mirror")
    assert ch.defaults.made_for_kids and ch.defaults.ai_content
    assert ch.defaults.category_id == "27"  # Education
    assert ch.ai_profile.kids_safe
    assert [(r.type, r.weekdays, r.time) for r in ch.slot_rules] == [
        ("Short", [0, 1, 2, 3, 4, 5], "19:00"), ("Long", [6], "19:00")]


def test_tokens_are_encrypted_at_rest(owner, google, yt_channel, repo):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    stored = json.dumps(repo.channels["UC_ink"], default=str)
    assert "1//refresh-UC_ink" not in stored  # what the Firestore console would show
    token = TokenCipher(FERNET_KEY).decrypt(repo.channels["UC_ink"]["token_enc"])
    assert token == {"refresh_token": "1//refresh-UC_ink", "scopes": [YT]}
    assert "1//refresh" not in owner.get("/channels").text


def test_unexpected_handle_warns_but_connects(owner, google, yt_channel, repo):
    page = connect(owner, google, yt_channel, "UC_other", "Cooking", "@cookingfun")
    assert "isn&#39;t one of the expected channels" in page.text
    assert repo.get_channel("UC_other").connected


def test_reconnect_keeps_edited_settings(owner, google, yt_channel, repo):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    ch = repo.get_channel("UC_ink")
    ch.defaults.default_playlist, ch.token_status = "Shorts 2026", "expired"
    repo.save_channel(ch)
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt", refresh="1//new-")
    ch = repo.get_channel("UC_ink")
    assert ch.defaults.default_playlist == "Shorts 2026"
    assert ch.token_status == "ok"
    assert TokenCipher(FERNET_KEY).decrypt(ch.token_enc)["refresh_token"] == "1//new-UC_ink"


@pytest.mark.parametrize("kwargs, message", [
    ({"scope": "openid"}, "YouTube permission wasn"),
    ({"refresh": None}, "long-lived token"),
])
def test_incomplete_consent_is_refused(owner, google, yt_channel, repo, kwargs, message):
    page = connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt", **kwargs)
    assert message in page.text
    assert repo.list_channels() == []


def test_login_without_a_channel_is_refused(owner, google, yt_channel, repo):
    start = owner.get("/auth/channel/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    yt_channel.info = None
    google.token_response = {"scope": YT, "refresh_token": "r"}
    page = owner.get(f"/auth/callback?code=c&state={state}")
    assert "has no YouTube channel" in page.text and repo.list_channels() == []


def test_cancelled_consent_changes_nothing(owner, repo):
    owner.get("/auth/channel/start", follow_redirects=False)
    page = owner.get("/auth/callback?error=access_denied")
    assert "cancelled" in page.text and repo.list_channels() == []


def test_channel_callback_after_sign_out_is_refused(client, google, yt_channel, repo):
    sign_in(client, google, OWNER)
    start = client.get("/auth/channel/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with client as c:
        c.cookies.clear()
    # a different browser (no session) can't complete someone else's connect
    assert client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False).status_code == 400
    assert repo.list_channels() == []


def test_missing_fernet_key_blocks_connect_with_instructions(google):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.repo import MemoryRepo
    from tests.conftest import make_settings

    c = TestClient(create_app(make_settings(fernet_key=""), repo=MemoryRepo()))
    sign_in(c, google, OWNER)
    r = c.get("/auth/channel/start", follow_redirects=False, headers={"accept": "text/html"})
    assert r.status_code == 503 and "FERNET_KEY" in r.text


# --- Sheets + Gmail account --------------------------------------------------

def test_account_connect_stores_encrypted_token_and_email(owner, google, repo):
    start = owner.get("/auth/account/start", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert set(q["scope"][0].split()) == {"openid", "email", *youtube.ACCOUNT_SCOPES}
    assert q["access_type"] == ["offline"]
    google.claims = {"email": "Sheets@Example.com", "email_verified": True, "nonce": q["nonce"][0]}
    google.token_response = {"scope": ACCOUNT_SCOPE, "refresh_token": "1//acct"}
    page = owner.get(f"/auth/callback?code=c&state={q['state'][0]}")
    assert "Connected sheets@example.com" in page.text
    s = repo.get_app_settings()
    assert s.account_status == "ok" and s.account_email == "sheets@example.com"
    assert s.notify_email == "sheets@example.com"
    assert "1//acct" not in json.dumps(repo.app_settings, default=str)
    assert owner.get("/").status_code == 200  # still signed in as the owner


def test_account_connect_needs_both_scopes(owner, google, repo):
    start = owner.get("/auth/account/start", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    google.claims = {"email": "x@example.com", "email_verified": True, "nonce": q["nonce"][0]}
    google.token_response = {"scope": "openid " + youtube.SHEETS_SCOPE, "refresh_token": "r"}
    page = owner.get(f"/auth/callback?code=c&state={q['state'][0]}")
    assert "both needed" in page.text and repo.get_app_settings().account_status == "missing"


# --- token health -------------------------------------------------------------

def test_revoked_channel_shows_expired_after_check(owner, google, yt_channel, repo, monkeypatch):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    connect(owner, google, yt_channel, "UC_ai", "AIPraveen", "@aipraveen18")
    seen = []

    def fake_check(token, client_id, client_secret):
        seen.append(token["refresh_token"])
        return "expired" if token["refresh_token"].endswith("UC_ink") else "ok"

    monkeypatch.setattr(token_service, "check_token", fake_check)
    page = owner.post("/channels/check", headers={"x-csrf-token": csrf(owner)}).text
    assert sorted(seen) == ["1//refresh-UC_ai", "1//refresh-UC_ink"]
    assert "Expired — reconnect" in page and "Ink &amp; Motion: Access was revoked" in page
    assert repo.get_channel("UC_ink").token_status == "expired"
    assert repo.get_channel("UC_ai").token_status == "ok"
    assert "Ink &amp; Motion: reconnect" in owner.get("/").text  # dashboard "Needs attention"


def test_temporary_google_error_does_not_mark_expired(owner, google, yt_channel, repo, monkeypatch):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")

    def flaky(*_):
        raise token_service.TokenCheckError("network error")

    monkeypatch.setattr(token_service, "check_token", flaky)
    owner.post("/channels/check", headers={"x-csrf-token": csrf(owner)})
    ch = repo.get_channel("UC_ink")
    assert ch.token_status == "ok" and "Couldn't check" in ch.token_error


def test_all_ok_check(owner, google, yt_channel, monkeypatch):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    monkeypatch.setattr(token_service, "check_token", lambda *_: "ok")
    assert "All connections are working" in owner.post("/channels/check", headers={"x-csrf-token": csrf(owner)}).text


def test_check_requires_csrf(owner):
    assert owner.post("/channels/check").status_code == 403


# --- channel settings form ------------------------------------------------------

def form_for(owner, **overrides):
    data = {
        "csrf_token": csrf(owner), "category_id": "27", "language": "hi", "default_playlist": " Weekly ",
        "colour": "#123ABC", "short_days": ["0", "2", "4"], "short_time": "18:30",
        "long_days": ["6"], "long_time": "10:00", "ai_audience": "Kids 5-9", "ai_tone": "playful",
        "ai_language": "en", "ai_title_style": "Short questions", "ai_hashtags": "science, #kids  #science",
        "ai_banned_words": "scary, gun", "made_for_kids": "on", "notify_subscribers": "on",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_edit_channel_settings(owner, google, yt_channel, repo):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    assert "Posting slots" in owner.get("/channels/UC_ink").text
    r = owner.post("/channels/UC_ink", data=form_for(owner))
    assert "Saved settings for Ink &amp; Motion" in r.text
    ch = repo.get_channel("UC_ink")
    assert ch.defaults.made_for_kids and not ch.defaults.ai_content and ch.defaults.notify_subscribers
    assert (ch.defaults.category_id, ch.defaults.language, ch.defaults.default_playlist) == ("27", "hi", "Weekly")
    assert ch.colour == "#123abc"
    assert [(r.type, r.weekdays, r.time) for r in ch.slot_rules] == [("Short", [0, 2, 4], "18:30"),
                                                                     ("Long", [6], "10:00")]
    assert ch.ai_profile.hashtags == ["#science", "#kids"]
    assert ch.ai_profile.banned_words == ["scary", "gun"]
    assert ch.ai_profile.kids_safe  # forced on for made-for-kids even though the box wasn't sent
    assert ch.token_enc  # editing settings never touches the token
    assert "Mon, Wed, Fri at 18:30" in owner.get("/channels").text


@pytest.mark.parametrize("override, message", [
    ({"short_time": "7pm"}, "Shorts schedule: time must look like 19:00"),
    ({"language": "English!"}, "Default language: language must be a code"),
    ({"category_id": "999"}, "Category: pick one from the list"),
    ({"colour": "red"}, "Colour: colour must look like"),
    ({"ai_hashtags": "#good #bad-tag"}, "Hashtags: hashtag"),
])
def test_invalid_settings_are_rejected_with_clear_message(owner, google, yt_channel, repo, override, message):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    before = repo.channels["UC_ink"]
    r = owner.post("/channels/UC_ink", data=form_for(owner, **override))
    assert r.status_code == 400 and message in r.text
    assert repo.channels["UC_ink"] == before


def test_empty_slot_days_warns(owner, google, yt_channel):
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    r = owner.post("/channels/UC_ink", data=form_for(owner, long_days=None))
    assert "will never get a slot" in r.text


def test_edit_unknown_channel_404_and_csrf_required(owner, google, yt_channel):
    assert owner.get("/channels/UC_nope").status_code == 404
    connect(owner, google, yt_channel, "UC_ink", "Ink & Motion", "@inkandmotionyt")
    assert owner.post("/channels/UC_ink", data={"language": "en"}).status_code == 403


def test_channel_pages_need_sign_in(client):
    for path in ("/channels", "/channels/UC_ink"):
        assert client.get(path, follow_redirects=False).status_code == 303
