"""Shared helpers: config, token bundle, Google API clients."""
import json
import os
from pathlib import Path

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent

# One scope covers upload, thumbnails, playlists and captions for a channel.
CHANNEL_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Main Google account (pravendalal@gmail.com): read Drive files, edit the sheet, send the summary email.
ACCOUNT_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

CATEGORY_IDS = {
    "film & animation": "1", "autos & vehicles": "2", "music": "10",
    "pets & animals": "15", "sports": "17", "travel & events": "19",
    "gaming": "20", "people & blogs": "22", "comedy": "23",
    "entertainment": "24", "news & politics": "25", "howto & style": "26",
    "education": "27", "science & technology": "28",
    "nonprofits & activism": "29",
}


def load_config():
    path = os.environ.get("CONFIG_FILE", ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def tokens_path():
    return Path(os.environ.get("TOKENS_FILE", ROOT / "tokens" / "tokens.json"))


def load_tokens():
    p = tokens_path()
    if not p.exists():
        raise SystemExit(f"Token file not found: {p}. Run auth_setup.py first.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(bundle):
    p = tokens_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)


def creds_from_info(info, scopes):
    creds = Credentials.from_authorized_user_info(info, scopes)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def account_services(bundle):
    if "account" not in bundle:
        raise SystemExit("Main account not authorised. Run: python src/auth_setup.py account")
    creds = creds_from_info(bundle["account"], ACCOUNT_SCOPES)
    return {
        "drive": build("drive", "v3", credentials=creds, cache_discovery=False),
        "sheets": build("sheets", "v4", credentials=creds, cache_discovery=False),
        "gmail": build("gmail", "v1", credentials=creds, cache_discovery=False),
    }


def youtube_for_handle(bundle, handle):
    """Return (youtube_client, channel_info) for the channel with this @handle."""
    want = handle.lower().lstrip("@")
    for cid, ch in bundle.get("channels", {}).items():
        if (ch.get("handle") or "").lower().lstrip("@") == want:
            creds = creds_from_info(ch["token"], CHANNEL_SCOPES)
            return build("youtube", "v3", credentials=creds, cache_discovery=False), {**ch, "id": cid}
    raise KeyError(f"No saved login for channel {handle}. Run: python src/auth_setup.py channel")
