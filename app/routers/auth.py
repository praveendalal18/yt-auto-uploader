"""Sign-in (/login, /auth/login, /auth/logout) and the shared OAuth callback (/auth/callback).

One redirect URI serves three flows; the purpose is remembered in the session with the state:
  signin  — who is using the app (openid email)
  channel — connect a YouTube channel (youtube.force-ssl, offline)
  account — connect the Google account for Sheets + Gmail (offline)
"""
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.security import csrf_token, is_allowed, safe_next
from app.services import google_signin
from app.templating import render

log = logging.getLogger(__name__)
router = APIRouter()


def start_oauth(request: Request, purpose: str, scopes: str = google_signin.SCOPES, offline: bool = False):
    settings = request.app.state.settings
    if not settings.oauth_client_id:
        raise HTTPException(503, "Google Sign-In is not set up yet (OAUTH_CLIENT_ID is empty).")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["oauth"] = {"state": state, "nonce": nonce, "purpose": purpose}
    url = google_signin.build_auth_url(settings.oauth_client_id, settings.redirect_uri, state, nonce,
                                       scopes=scopes, offline=offline)
    return RedirectResponse(url, status_code=303)


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    if request.session.get("user"):
        return RedirectResponse(safe_next(next), status_code=303)
    request.session["next"] = safe_next(next)
    configured = bool(request.app.state.settings.oauth_client_id)
    return render(request, "login.html", {"configured": configured})


@router.get("/auth/login")
def start_sign_in(request: Request):
    return start_oauth(request, "signin")


@router.get("/auth/callback")
def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    from app.routers import channels  # local import: channels imports this module

    settings = request.app.state.settings
    pending = request.session.pop("oauth", None) or {}
    purpose = pending.get("purpose", "signin")
    if error:
        if purpose == "signin":
            return render(request, "login.html", {"configured": True, "error": "Sign-in was cancelled."})
        return channels.cancelled(request)
    if not pending.get("state") or not secrets.compare_digest(pending["state"], state) or not code:
        raise HTTPException(400, "Sign-in link expired or was tampered with. Please start again.")
    if purpose != "signin" and not request.session.get("user"):
        raise HTTPException(400, "You were signed out while connecting. Sign in and try again.")
    try:
        tokens = google_signin.exchange_code(
            code, settings.oauth_client_id, settings.oauth_client_secret, settings.redirect_uri
        )
        claims = {}
        if purpose in ("signin", "account"):
            claims = google_signin.verify_id_token(tokens.get("id_token", ""), settings.oauth_client_id)
            if claims.get("nonce") != pending.get("nonce"):
                raise HTTPException(400, "Sign-in response did not match this browser. Please start again.")
    except google_signin.SignInError as e:
        if purpose == "signin":
            return render(request, "login.html", {"configured": True, "error": str(e)}, status_code=400)
        return channels.failed(request, str(e))

    if purpose == "channel":
        return channels.complete_channel(request, tokens)
    if purpose == "account":
        return channels.complete_account(request, tokens, claims)
    return _complete_sign_in(request, claims)


def _complete_sign_in(request: Request, claims: dict):
    email = (claims.get("email") or "").lower()
    if not claims.get("email_verified") or not is_allowed(request, email):
        log.warning("sign-in refused for a non-allowlisted account")  # no email in logs (PII)
        request.session.clear()
        raise HTTPException(403, "This Google account is not allowed to use this app.")
    next_path = safe_next(request.session.get("next"))
    request.session.clear()  # fresh session after login (prevents session fixation)
    request.session["user"] = {"email": email, "name": claims.get("name", ""), "picture": claims.get("picture", "")}
    csrf_token(request)
    return RedirectResponse(next_path, status_code=303)


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
