"""App settings, read from environment variables (and a local .env file in development)."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

DEFAULT_BASE_URL = "http://localhost:8000"


def parse_emails(raw: str) -> frozenset[str]:
    """'a@x.com, B@x.com' -> {'a@x.com', 'b@x.com'} (case-insensitive, blanks dropped)."""
    return frozenset(e.strip().lower() for e in (raw or "").split(",") if e.strip())


def _bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    session_secret: str
    allowed_emails: frozenset[str] = field(default_factory=frozenset)
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    base_url: str = DEFAULT_BASE_URL
    google_cloud_project: str = "yt-auto-uploader"
    audit_approved: bool = False
    contact_email: str = ""
    timezone: str = "Asia/Kolkata"
    ping_token: str = ""

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def public_contact(self) -> str:
        return self.contact_email or next(iter(sorted(self.allowed_emails)), "")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)  # no-op when there is no .env file
        secret = os.environ.get("SESSION_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError(
                "SESSION_SECRET is missing or shorter than 32 characters. "
                "Create one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\"  "
                "and put it in your .env file."
            )
        return cls(
            session_secret=secret,
            allowed_emails=parse_emails(os.environ.get("ALLOWED_EMAILS", "")),
            oauth_client_id=os.environ.get("OAUTH_CLIENT_ID", ""),
            oauth_client_secret=os.environ.get("OAUTH_CLIENT_SECRET", ""),
            base_url=os.environ.get("BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            google_cloud_project=os.environ.get("GOOGLE_CLOUD_PROJECT", "yt-auto-uploader"),
            audit_approved=_bool(os.environ.get("AUDIT_APPROVED")),
            contact_email=os.environ.get("CONTACT_EMAIL", ""),
            timezone=os.environ.get("TZ", "Asia/Kolkata") or "Asia/Kolkata",
            ping_token=os.environ.get("PING_TOKEN", ""),
        )
