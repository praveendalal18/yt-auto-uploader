"""Sign-in guard (allowlist) and CSRF protection."""
import hmac
import secrets

from fastapi import HTTPException, Request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LoginRequired(Exception):
    """Raised for signed-out visitors; turned into a redirect to /login."""


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def csrf_protect(request: Request) -> None:
    """Every POST/PUT/PATCH/DELETE must echo the session's CSRF token
    (HTMX sends it as the X-CSRF-Token header; plain forms as a csrf_token field)."""
    if request.method in SAFE_METHODS:
        return
    expected = request.session.get("csrf")
    sent = request.headers.get("x-csrf-token")
    if not sent:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            sent = (await request.form()).get("csrf_token")
    if not expected or not isinstance(sent, str) or not hmac.compare_digest(expected, sent):
        raise HTTPException(status_code=403, detail="Security check failed. Reload the page and try again.")


def is_allowed(request: Request, email: str | None) -> bool:
    return bool(email) and email.lower() in request.app.state.settings.allowed_emails


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise LoginRequired()
    # Re-check on every request, so removing an email from ALLOWED_EMAILS locks it out at once.
    if not is_allowed(request, user.get("email")):
        request.session.clear()
        raise HTTPException(status_code=403, detail="This Google account is not allowed to use this app.")
    return user


def safe_next(path: str | None) -> str:
    """Only allow same-site relative paths after sign-in (no open redirects)."""
    if path and path.startswith("/") and not path.startswith(("//", "/\\")):
        return path
    return "/"
