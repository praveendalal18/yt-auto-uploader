from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from tests.conftest import OWNER, sign_in

HTML = {"accept": "text/html"}


def csrf_of(client) -> str:
    page = client.get("/", headers=HTML)
    marker = 'name="csrf-token" content="'
    start = page.text.index(marker) + len(marker)
    return page.text[start:page.text.index('"', start)]


# --- allowlist ---------------------------------------------------------------

def test_signed_out_visitor_is_sent_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_owner_reaches_dashboard(client, google):
    r = sign_in(client, google, OWNER)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = client.get("/", headers=HTML)
    assert page.status_code == 200
    assert "Dashboard" in page.text and OWNER in page.text


def test_allowlist_ignores_email_case(client, google):
    sign_in(client, google, "Owner@Example.COM")
    assert client.get("/").status_code == 200


def test_other_google_account_gets_403(client, google):
    r = sign_in(client, google, "stranger@gmail.com")
    assert r.status_code == 403
    # ...and is still not signed in afterwards
    assert client.get("/", follow_redirects=False).status_code == 303


def test_403_page_is_html_for_browsers(client, google):
    start = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = parse_qs(urlparse(start.headers["location"]).query)["nonce"][0]
    google.claims = {"email": "stranger@gmail.com", "email_verified": True, "nonce": nonce}
    r = client.get(f"/auth/callback?code=x&state={state}", headers=HTML, follow_redirects=False)
    assert r.status_code == 403
    assert "Access denied" in r.text


def test_unverified_email_is_refused(client, google):
    assert sign_in(client, google, OWNER, verified=False).status_code == 403
    assert client.get("/", follow_redirects=False).status_code == 303


def test_lookalike_email_is_refused(client, google):
    assert sign_in(client, google, OWNER + ".evil.com").status_code == 403
    assert sign_in(client, google, "x" + OWNER).status_code == 403


def test_empty_allowlist_lets_nobody_in(google):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.repo import MemoryRepo
    from tests.conftest import make_settings

    c = TestClient(create_app(make_settings(allowed_emails=frozenset()), repo=MemoryRepo()))
    assert sign_in(c, google, OWNER).status_code == 403


def test_removing_email_from_allowlist_locks_out_live_session(app, client, google):
    sign_in(client, google, OWNER)
    assert client.get("/").status_code == 200
    app.state.settings = replace(app.state.settings, allowed_emails=frozenset({"new@example.com"}))
    assert client.get("/").status_code == 403
    assert client.get("/", follow_redirects=False).status_code == 303  # session was wiped


# --- sign-in flow hardening --------------------------------------------------

def test_login_redirects_to_google_with_expected_params(client):
    r = client.get("/auth/login", follow_redirects=False)
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["client_id"] == ["client-123.apps.googleusercontent.com"]
    assert q["redirect_uri"] == ["http://localhost:8000/auth/callback"]
    assert q["scope"] == ["openid email profile"]
    assert q["state"][0] and q["nonce"][0]


def test_callback_with_wrong_state_is_rejected(client, google):
    client.get("/auth/login", follow_redirects=False)
    r = client.get("/auth/callback?code=abc&state=forged", follow_redirects=False)
    assert r.status_code == 400
    assert google.exchanged == []  # never even talked to Google


def test_callback_without_starting_login_is_rejected(client, google):
    assert client.get("/auth/callback?code=abc&state=x", follow_redirects=False).status_code == 400


def test_state_cannot_be_replayed(client, google):
    start = client.get("/auth/login", follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    google.claims = {"email": OWNER, "email_verified": True, "nonce": q["nonce"][0]}
    url = f"/auth/callback?code=abc&state={q['state'][0]}"
    assert client.get(url, follow_redirects=False).status_code == 303
    client.post("/auth/logout", headers={"x-csrf-token": csrf_of(client)})
    assert client.get(url, follow_redirects=False).status_code == 400


def test_nonce_mismatch_is_rejected(client, google):
    assert sign_in(client, google, OWNER, nonce_override="other").status_code == 400


def test_cancelled_google_consent_shows_message(client):
    client.get("/auth/login", follow_redirects=False)
    r = client.get("/auth/callback?error=access_denied")
    assert r.status_code == 200 and "cancelled" in r.text


def test_next_path_is_kept_but_open_redirects_are_not(client, google):
    client.get("/login?next=/privacy")
    assert sign_in(client, google, OWNER).headers["location"] == "/privacy"
    client.post("/auth/logout", headers={"x-csrf-token": csrf_of(client)})
    client.get("/login?next=//evil.com")
    assert sign_in(client, google, OWNER).headers["location"] == "/"


def test_login_page_explains_missing_oauth_setup(google):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.repo import MemoryRepo
    from tests.conftest import make_settings

    c = TestClient(create_app(make_settings(oauth_client_id=""), repo=MemoryRepo()))
    assert "OAUTH_CLIENT_ID" in c.get("/login").text
    assert c.get("/auth/login", follow_redirects=False).status_code == 503


def test_htmx_request_when_signed_out_gets_hx_redirect(client):
    r = client.get("/", headers={"hx-request": "true"})
    assert r.status_code == 401 and r.headers["hx-redirect"] == "/login"


# --- CSRF ---------------------------------------------------------------------

def test_logout_without_csrf_token_is_refused(client, google):
    sign_in(client, google, OWNER)
    assert client.post("/auth/logout", follow_redirects=False).status_code == 403
    assert client.post("/auth/logout", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.get("/").status_code == 200  # still signed in


def test_logout_with_csrf_header_works(client, google):
    sign_in(client, google, OWNER)
    r = client.post("/auth/logout", headers={"x-csrf-token": csrf_of(client)}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_logout_with_csrf_form_field_works(client, google):
    sign_in(client, google, OWNER)
    r = client.post("/auth/logout", data={"csrf_token": csrf_of(client)}, follow_redirects=False)
    assert r.status_code == 303


# --- public pages and headers ------------------------------------------------

def test_privacy_and_terms_are_public(client):
    for path in ("/privacy", "/terms"):
        r = client.get(path)
        assert r.status_code == 200
        assert "youtube.com/t/terms" in r.text
        assert "policies.google.com/privacy" in r.text


def test_healthz_and_security_headers(client):
    r = client.get("/healthz")
    assert r.json() == {"ok": True}
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_audit_banner_shows_until_approved(app, client, google):
    sign_in(client, google, OWNER)
    assert "audit not approved" in client.get("/").text
    app.state.settings = replace(app.state.settings, audit_approved=True)
    assert "audit not approved" not in client.get("/").text
