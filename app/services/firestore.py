"""Firestore client. Uses the local emulator when FIRESTORE_EMULATOR_HOST is set."""
import os
from functools import lru_cache


def make_client(project: str):
    from google.cloud import firestore

    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        # The emulator needs no real credentials; this keeps local dev free of Google logins.
        from google.auth.credentials import AnonymousCredentials

        return firestore.Client(project=project, credentials=AnonymousCredentials())
    return firestore.Client(project=project)


@lru_cache(maxsize=1)
def get_db():
    return make_client(os.environ.get("GOOGLE_CLOUD_PROJECT", "yt-auto-uploader"))


def ping() -> None:
    """Touch the database: write a heartbeat timestamp and read it back (2 operations/day)."""
    from google.cloud import firestore as fs

    ref = get_db().collection("system").document("heartbeat")
    ref.set({"last_ping": fs.SERVER_TIMESTAMP}, merge=True)
    ref.get()
