"""Token health checks: refresh each stored token; Google answers invalid_grant once access is revoked/expired."""
import logging

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request

from app.services.crypto import TokenCipher, TokenDecryptError
from app.services.youtube import credentials_from_token
from app.timeutil import now_utc

log = logging.getLogger(__name__)
RECONNECT = "Access was revoked or expired. Reconnect."


class TokenCheckError(Exception):
    """Temporary problem (network, Google outage) — the token may still be fine."""


def check_token(token: dict, client_id: str, client_secret: str) -> str:
    """Returns 'ok' or 'expired'. Raises TokenCheckError when Google couldn't be asked. Uses no API quota."""
    creds = credentials_from_token(token, client_id, client_secret)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        if "invalid_grant" in str(e) or "invalid_client" in str(e) or "unauthorized_client" in str(e):
            return "expired"
        raise TokenCheckError(type(e).__name__) from e
    except TransportError as e:
        raise TokenCheckError("network error") from e
    return "ok"


def check_all(repo, cipher: TokenCipher, client_id: str, client_secret: str, checker=None) -> list[str]:
    """Check every connected channel + the Sheets/Gmail account. Returns human-readable problems."""
    checker = checker or check_token
    problems: list[str] = []

    def run(blob: str | None) -> tuple[str | None, str]:
        if not blob:
            return None, ""
        try:
            return checker(cipher.decrypt(blob), client_id, client_secret), ""
        except TokenDecryptError as e:
            return "expired", str(e)
        except TokenCheckError as e:
            log.warning("token check skipped: %s", e)
            return None, f"Couldn't check just now ({e}). Will retry."

    for ch in repo.list_channels():
        if not ch.connected:
            continue
        status, err = run(ch.token_enc)
        if status:
            ch.token_status = status
            ch.token_error = err or (RECONNECT if status == "expired" else "")
            ch.token_checked_at = now_utc()
        elif err:
            ch.token_error = err
        if ch.token_status != "ok":
            problems.append(f"{ch.title}: {ch.token_error or RECONNECT}")
        repo.save_channel(ch)

    s = repo.get_app_settings()
    if s.account_token_enc:
        status, err = run(s.account_token_enc)
        if status:
            s.account_status = status
            s.account_error = err or (RECONNECT if status == "expired" else "")
            s.account_checked_at = now_utc()
        elif err:
            s.account_error = err
        if s.account_status not in ("ok", "missing"):
            problems.append(f"Google account (Sheets + Gmail): {s.account_error or RECONNECT}")
        repo.save_app_settings(s)
    return problems
