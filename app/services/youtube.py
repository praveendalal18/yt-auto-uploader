"""YouTube Data API helpers. (Upload logic moves here from src/uploader.py in Phase 3.)"""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.services.google_signin import TOKEN_URL

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
ACCOUNT_SCOPES = [SHEETS_SCOPE, GMAIL_SEND_SCOPE]


def credentials_from_token(token: dict, client_id: str, client_secret: str) -> Credentials:
    """Rebuild Google credentials from our stored {refresh_token, scopes} (client secret comes from config)."""
    return Credentials(
        token=None, refresh_token=token["refresh_token"], token_uri=TOKEN_URL,
        client_id=client_id, client_secret=client_secret, scopes=token.get("scopes"),
    )


def fetch_my_channel(access_token: str) -> dict | None:
    """The channel this login belongs to: {id, title, handle, thumbnail_url}, or None. Costs 1 quota unit."""
    yt = build("youtube", "v3", credentials=Credentials(token=access_token), cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        return None
    sn = items[0]["snippet"]
    return {
        "id": items[0]["id"],
        "title": sn.get("title", ""),
        "handle": sn.get("customUrl", ""),
        "thumbnail_url": ((sn.get("thumbnails") or {}).get("default") or {}).get("url", ""),
    }
