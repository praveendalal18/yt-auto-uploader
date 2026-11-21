"""One-time login. Run on YOUR laptop (it opens a browser window).

    python src/auth_setup.py account    # once: pravendalal@gmail.com (Drive + Sheet + email)
    python src/auth_setup.py channel    # 4 times: pick a different channel each time
    python src/auth_setup.py list       # show what is saved

No password is stored — only Google OAuth tokens in tokens/tokens.json.
Keep that file private (never email it or put it in a public repo).
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from common import ACCOUNT_SCOPES, CHANNEL_SCOPES, ROOT, save_tokens, tokens_path

CLIENT_SECRET = ROOT / "client_secret.json"


def run_flow(scopes):
    if not CLIENT_SECRET.exists():
        raise SystemExit(f"Put the OAuth client file from Google Cloud here: {CLIENT_SECRET}")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), scopes)
    return flow.run_local_server(
        port=0, access_type="offline", prompt="select_account consent",
        success_message="Done! You can close this tab and go back to the terminal.",
    )


def load_bundle():
    p = tokens_path()
    return json.load(open(p, encoding="utf-8")) if p.exists() else {"channels": {}}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    bundle = load_bundle()

    if mode == "account":
        print("A browser will open. Choose pravendalal@gmail.com (the personal account, not a channel).")
        creds = run_flow(ACCOUNT_SCOPES)
        bundle["account"] = json.loads(creds.to_json())
        save_tokens(bundle)
        print("Main account saved.")

    elif mode == "channel":
        print("A browser will open. Choose pravendalal@gmail.com, then pick the CHANNEL "
              "(Ink & Motion / Mirrorkin Press / Kidz Curious Labs / AIPraveen).")
        creds = run_flow(CHANNEL_SCOPES)
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
        if not items:
            raise SystemExit("That login has no YouTube channel. Try again and pick a channel.")
        ch = items[0]
        bundle.setdefault("channels", {})[ch["id"]] = {
            "title": ch["snippet"]["title"],
            "handle": ch["snippet"].get("customUrl", ""),
            "token": json.loads(creds.to_json()),
        }
        save_tokens(bundle)
        print(f"Saved channel: {ch['snippet']['title']} ({ch['snippet'].get('customUrl', '')})")

    elif mode == "list":
        print("Main account:", "saved" if "account" in bundle else "NOT saved")
        for cid, ch in bundle.get("channels", {}).items():
            print(f"  {ch['title']:<22} {ch['handle']:<20} {cid}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
