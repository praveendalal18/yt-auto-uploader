"""/channels: connect/reconnect YouTube channels + the Sheets/Gmail account, edit defaults, check tokens."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.models import WEEKDAYS, Channel
from app.routers.auth import start_oauth
from app.security import require_user
from app.services import tokens as token_service
from app.services import youtube
from app.services.crypto import CipherNotConfigured, TokenCipher
from app.services.seed import CATEGORIES, generic_channel, match_expected, norm_handle
from app.templating import flash, render
from app.timeutil import now_utc

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_user)])

FIELD_LABELS = {
    "colour": "Colour", "defaults.language": "Default language", "defaults.default_playlist": "Default playlist",
    "slot_rules.0": "Shorts schedule", "slot_rules.1": "Long videos schedule",
    "ai_profile.audience": "Audience", "ai_profile.tone": "Tone", "ai_profile.language": "AI language",
    "ai_profile.title_style": "Title style", "ai_profile.hashtags": "Hashtags",
}


def get_cipher(request: Request) -> TokenCipher:
    try:
        return TokenCipher(request.app.state.settings.fernet_key)
    except CipherNotConfigured as e:
        raise HTTPException(503, str(e)) from e


def back_to_channels() -> RedirectResponse:
    return RedirectResponse("/channels", status_code=303)


def cancelled(request: Request):
    flash(request, "warn", "Connecting was cancelled on Google's screen. Nothing was changed.")
    return back_to_channels()


def failed(request: Request, message: str):
    flash(request, "error", message)
    return back_to_channels()


def channel_rows(request: Request) -> list[dict]:
    """The expected channels (from config.yaml) in order, matched to connected ones, then any extras."""
    connected = request.app.state.repo.list_channels()
    rows, used = [], set()
    for exp in request.app.state.expected:
        ch = next((c for c in connected if norm_handle(c.handle) == norm_handle(exp.handle)), None)
        if ch:
            used.add(ch.id)
        rows.append({"expected": exp, "channel": ch})
    rows += [{"expected": None, "channel": c} for c in connected if c.id not in used]
    return rows


# --- list + connect ----------------------------------------------------------

@router.get("/channels")
def channels_page(request: Request):
    return render(request, "channels.html", {
        "rows": channel_rows(request),
        "account": request.app.state.repo.get_app_settings(),
        "categories": CATEGORIES,
    })


@router.get("/auth/channel/start")
def start_channel(request: Request):
    get_cipher(request)  # fail before sending the user through Google if encryption isn't set up
    return start_oauth(request, "channel", scopes=youtube.YOUTUBE_SCOPE, offline=True)


@router.get("/auth/account/start")
def start_account(request: Request):
    get_cipher(request)
    return start_oauth(request, "account", scopes="openid email " + " ".join(youtube.ACCOUNT_SCOPES), offline=True)


def complete_channel(request: Request, tokens: dict):
    scopes = (tokens.get("scope") or "").split()
    if youtube.YOUTUBE_SCOPE not in scopes:
        return failed(request, "YouTube permission wasn't granted. On Google's screen, tick the box that lets "
                               "the app manage your YouTube account, then try again.")
    if not tokens.get("refresh_token"):
        return failed(request, "Google didn't send a long-lived token. Please try connecting again.")
    cipher = get_cipher(request)
    try:
        info = youtube.fetch_my_channel(tokens["access_token"])
    except Exception:
        log.exception("channels.list failed during connect")
        return failed(request, "Couldn't read the channel from YouTube. Please try again in a minute.")
    if not info:
        return failed(request, "That Google login has no YouTube channel. Try again, and on Google's screen pick "
                               "the channel itself (e.g. Ink & Motion), not just your personal account.")

    repo, now = request.app.state.repo, now_utc()
    expected = match_expected(request.app.state.expected, info["handle"])
    ch = repo.get_channel(info["id"])
    if ch is None:
        ch = (expected.new_channel(info["id"], info["title"], info["handle"]) if expected
              else generic_channel(info["id"], info["title"], info["handle"],
                                   len(request.app.state.expected) + len(repo.list_channels())))
    ch.title, ch.handle, ch.thumbnail_url = info["title"], info["handle"], info["thumbnail_url"]
    ch.connected, ch.token_status, ch.token_error = True, "ok", ""
    ch.token_enc = cipher.encrypt({"refresh_token": tokens["refresh_token"], "scopes": scopes})
    ch.token_checked_at = ch.connected_at = now
    repo.save_channel(ch)
    if not expected:
        names = ", ".join(e.handle for e in request.app.state.expected)
        flash(request, "warn", f"{info['handle'] or info['title']} isn't one of the expected channels ({names}). "
                               "It was connected anyway — check it's the right one.")
    flash(request, "ok", f"Connected {info['title']} ({info['handle']}).")
    return back_to_channels()


def complete_account(request: Request, tokens: dict, claims: dict):
    scopes = (tokens.get("scope") or "").split()
    missing = [s for s in youtube.ACCOUNT_SCOPES if s not in scopes]
    if missing:
        return failed(request, "Google Sheets and Gmail permissions are both needed. Tick both boxes on Google's "
                               "screen and try again.")
    if not tokens.get("refresh_token"):
        return failed(request, "Google didn't send a long-lived token. Please try connecting again.")
    repo = request.app.state.repo
    s = repo.get_app_settings()
    s.account_token_enc = get_cipher(request).encrypt({"refresh_token": tokens["refresh_token"], "scopes": scopes})
    s.account_email = (claims.get("email") or "").lower()
    s.account_status, s.account_error, s.account_checked_at = "ok", "", now_utc()
    s.notify_email = s.notify_email or s.account_email
    repo.save_app_settings(s)
    flash(request, "ok", f"Connected {s.account_email} for Google Sheets and Gmail.")
    return back_to_channels()


@router.post("/channels/check")
def check_tokens(request: Request):
    settings = request.app.state.settings
    problems = token_service.check_all(request.app.state.repo, get_cipher(request),
                                       settings.oauth_client_id, settings.oauth_client_secret)
    for p in problems:
        flash(request, "error", p)
    if not problems:
        flash(request, "ok", "All connections are working.")
    return back_to_channels()


# --- edit one channel ---------------------------------------------------------

def _load(request: Request, channel_id: str) -> Channel:
    ch = request.app.state.repo.get_channel(channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found. Connect it first.")
    return ch


def _edit_page(request: Request, ch: Channel, errors: list[str] | None = None, status_code: int = 200):
    return render(request, "channel_edit.html", {
        "ch": ch, "categories": CATEGORIES, "weekdays": WEEKDAYS, "errors": errors or [],
        "rules": {r.type: r for r in ch.slot_rules},
    }, status_code=status_code)


@router.get("/channels/{channel_id}")
def edit_channel(request: Request, channel_id: str):
    return _edit_page(request, _load(request, channel_id))


def _days(form, name: str) -> list[int]:
    out = []
    for v in form.getlist(name):
        try:
            out.append(int(v))
        except ValueError:
            continue
    return out


def _split(text: str, by_comma_only: bool = False) -> list[str]:
    text = text or ""
    parts = text.split(",") if by_comma_only else text.replace(",", " ").split()
    return [p.strip() for p in parts if p.strip()]


def _friendly(e: ValidationError) -> list[str]:
    msgs = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        label = next((v for k, v in FIELD_LABELS.items() if loc == k or loc.startswith(k + ".")), loc)
        msgs.append(f"{label}: {err['msg'].removeprefix('Value error, ')}")
    return msgs


@router.post("/channels/{channel_id}")
async def save_channel(request: Request, channel_id: str):
    ch = _load(request, channel_id)
    form = await request.form()
    errors = []
    category = form.get("category_id", ch.defaults.category_id)
    if category not in CATEGORIES:
        errors.append("Category: pick one from the list")
    data = ch.model_dump()
    data.update(
        colour=form.get("colour", ch.colour),
        defaults={
            "made_for_kids": "made_for_kids" in form,
            "ai_content": "ai_content" in form,
            "notify_subscribers": "notify_subscribers" in form,
            "category_id": category,
            "language": form.get("language", ""),
            "default_playlist": (form.get("default_playlist") or "").strip(),
        },
        slot_rules=[
            {"type": "Short", "weekdays": _days(form, "short_days"), "time": form.get("short_time", "")},
            {"type": "Long", "weekdays": _days(form, "long_days"), "time": form.get("long_time", "")},
        ],
        ai_profile={
            "audience": (form.get("ai_audience") or "").strip(),
            "tone": (form.get("ai_tone") or "").strip(),
            "language": form.get("ai_language", ""),
            "title_style": (form.get("ai_title_style") or "").strip(),
            "hashtags": _split(form.get("ai_hashtags", "")),
            "banned_words": _split(form.get("ai_banned_words", ""), by_comma_only=True),
            "kids_safe": "ai_kids_safe" in form,
        },
    )
    try:
        updated = Channel.model_validate(data)
    except ValidationError as e:
        errors += _friendly(e)
        updated = None
    if errors:
        return _edit_page(request, ch, errors, status_code=400)
    request.app.state.repo.save_channel(updated)
    flash(request, "ok", f"Saved settings for {updated.title}.")
    if not all(r.weekdays for r in updated.slot_rules):
        flash(request, "warn", "One schedule has no days ticked, so that video type will never get a slot.")
    return back_to_channels()
