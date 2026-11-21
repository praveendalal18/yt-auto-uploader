import os
from urllib.parse import parse_qs, urlparse

# Must be set before app.main is imported (it builds the app at import time).
os.environ.setdefault("SESSION_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("ALLOWED_EMAILS", "owner@example.com")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import google_signin  # noqa: E402
from app.services.repo import MemoryRepo  # noqa: E402

FERNET_KEY = "uI9rP7nFJ0tqS6wZ0rWq2n3o3QnCzH8y7o6d4l2k1a0="

OWNER = "owner@example.com"


def make_settings(**overrides) -> Settings:
    base = dict(
        session_secret="s" * 48,
        allowed_emails=frozenset({OWNER}),
        oauth_client_id="client-123.apps.googleusercontent.com",
        oauth_client_secret="shh",
        base_url="http://localhost:8000",
        ping_token="ping-token-abc",
        fernet_key=FERNET_KEY,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def repo():
    return MemoryRepo()


@pytest.fixture
def app(repo):
    return create_app(make_settings(), repo=repo)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def google(monkeypatch):
    """Fake Google: whatever claims you set in google.claims come back from the ID token."""

    class FakeGoogle:
        claims: dict = {}
        exchanged: list = []
        token_response: dict = {}  # extra fields Google's token endpoint returns (refresh_token, scope…)

    fake = FakeGoogle()

    def exchange(code, client_id, client_secret, redirect_uri):
        fake.exchanged.append((code, client_id, redirect_uri))
        return {"id_token": "fake-id-token", "access_token": "fake-access", **fake.token_response}

    def verify(token, client_id):
        assert token == "fake-id-token"
        return dict(fake.claims)

    monkeypatch.setattr(google_signin, "exchange_code", exchange)
    monkeypatch.setattr(google_signin, "verify_id_token", verify)
    return fake


def sign_in(client, google, email, *, verified=True, nonce_override=None, **extra):
    """Run the full /auth/login -> Google -> /auth/callback flow. Returns the callback response."""
    start = client.get("/auth/login", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)
    state, nonce = params["state"][0], params["nonce"][0]
    google.claims = {"email": email, "email_verified": verified,
                     "nonce": nonce_override or nonce, "name": "Test", **extra}
    return client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
