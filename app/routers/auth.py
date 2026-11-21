"""/login, /auth/login, /auth/callback, /auth/logout."""
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.security import csrf_token, is_allowed, safe_next
from app.services import google_signin
from app.templating import render

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    if request.session.get("user"):
        return RedirectResponse(safe_next(next), status_code=303)
    request.session["next"] = safe_next(next)
    configured = bool(request.app.state.settings.oauth_client_id)
    return render(request, "login.html", {"configured": configured})


@router.get("/auth/login")
def start_sign_in(request: Request):
    settings = request.app.state.settings
    if not settings.oauth_client_id:
        raise HTTPException(503, "Google Sign-In is not set up yet (OAUTH_CLIENT_ID is empty).")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_nonce"] = nonce
    url = google_signin.build_auth_url(settings.oauth_client_id, settings.redirect_uri, state, nonce)
    return RedirectResponse(url, status_code=303)


@router.get("/auth/callback")
def finish_sign_in(request: Request, state: str = "", code: str = "", error: str = ""):
    settings = request.app.state.settings
    expected_state = request.session.pop("oauth_state", None)
    nonce = request.session.pop("oauth_nonce", None)
    if error:
        return render(request, "login.html", {"configured": True, "error": "Sign-in was cancelled."})
    if not expected_state or not secrets.compare_digest(expected_state, state) or not code:
        raise HTTPException(400, "Sign-in link expired or was tampered with. Please start again.")
    try:
        tokens = google_signin.exchange_code(
            code, settings.oauth_client_id, settings.oauth_client_secret, settings.redirect_uri
        )
        claims = google_signin.verify_id_token(tokens.get("id_token", ""), settings.oauth_client_id)
    except google_signin.SignInError as e:
        return render(request, "login.html", {"configured": True, "error": str(e)}, status_code=400)

    if not nonce or claims.get("nonce") != nonce:
        raise HTTPException(400, "Sign-in response did not match this browser. Please start again.")
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
