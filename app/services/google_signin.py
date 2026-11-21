"""Google Sign-In (OpenID Connect, authorization-code flow) — identity only, no API scopes."""
from urllib.parse import urlencode

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"


class SignInError(Exception):
    pass


def build_auth_url(client_id: str, redirect_uri: str, state: str, nonce: str,
                   scopes: str = SCOPES, offline: bool = False) -> str:
    """offline=True asks for a refresh token (used to connect channels / the Sheets+Gmail account)."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "nonce": nonce,
        "prompt": "select_account consent" if offline else "select_account",
    }
    if offline:
        params["access_type"] = "offline"
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise SignInError("Could not reach Google to finish sign-in.") from e
    if resp.status_code != 200:
        raise SignInError("Google rejected the sign-in code. Please try again.")
    return resp.json()


def verify_id_token(token: str, client_id: str) -> dict:
    """Checks signature, audience, issuer and expiry. Returns the token claims."""
    try:
        return id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
    except ValueError as e:
        raise SignInError("Google's sign-in response could not be verified.") from e
