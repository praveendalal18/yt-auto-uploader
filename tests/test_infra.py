from datetime import UTC, datetime

import pytest

from app.config import Settings, parse_emails
from app.services import firestore
from app.timeutil import fmt_ist


def test_parse_emails():
    assert parse_emails(" A@x.com, b@X.com ,,") == frozenset({"a@x.com", "b@x.com"})
    assert parse_emails("") == frozenset()


def test_settings_require_a_strong_session_secret(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        Settings.from_env()


def test_settings_from_env(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("SESSION_SECRET", "z" * 40)
    monkeypatch.setenv("ALLOWED_EMAILS", "Me@Gmail.com")
    monkeypatch.setenv("BASE_URL", "https://app.example.run.app/")
    monkeypatch.setenv("AUDIT_APPROVED", "true")
    s = Settings.from_env()
    assert s.allowed_emails == frozenset({"me@gmail.com"})
    assert s.redirect_uri == "https://app.example.run.app/auth/callback"
    assert s.secure_cookies and s.audit_approved


def test_fmt_ist():
    assert fmt_ist(datetime(2025, 11, 30, 13, 30, tzinfo=UTC)) == "Sun 30 Nov, 7:00 PM"
    assert fmt_ist(datetime(2025, 11, 30, 18, 30)) == "Mon 1 Dec, 12:00 AM"  # naive = UTC
    assert fmt_ist(None) == ""


def test_firestore_uses_emulator_without_real_credentials(monkeypatch):
    from google.auth.credentials import AnonymousCredentials

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    db = firestore.make_client("demo-project")
    assert db.project == "demo-project"
    assert isinstance(db._credentials, AnonymousCredentials)


# --- daily DB keep-alive -----------------------------------------------------

def test_db_ping_is_hidden_without_the_token(client, monkeypatch):
    called = []
    monkeypatch.setattr(firestore, "ping", lambda: called.append(1))
    assert client.get("/healthz/db").status_code == 404
    assert client.get("/healthz/db", headers={"x-ping-token": "wrong"}).status_code == 404
    assert called == []


def test_db_ping_disabled_when_no_token_configured(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    monkeypatch.setattr(firestore, "ping", lambda: None)
    c = TestClient(create_app(make_settings(ping_token="")))
    assert c.get("/healthz/db", headers={"x-ping-token": ""}).status_code == 404


def test_db_ping_touches_firestore(client, monkeypatch):
    called = []
    monkeypatch.setattr(firestore, "ping", lambda: called.append(1))
    r = client.get("/healthz/db", headers={"x-ping-token": "ping-token-abc"})
    assert r.json() == {"ok": True, "db": "ok"} and called == [1]


def test_db_ping_reports_failure(client, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(firestore, "ping", boom)
    assert client.get("/healthz/db", headers={"x-ping-token": "ping-token-abc"}).status_code == 503


def test_ping_writes_and_reads_heartbeat(monkeypatch):
    class Ref:
        def __init__(self):
            self.ops = []

        def set(self, data, merge):
            self.ops.append(("set", merge))

        def get(self):
            self.ops.append(("get",))

    ref = Ref()

    class DB:
        def collection(self, name):
            assert name == "system"
            return self

        def document(self, name):
            assert name == "heartbeat"
            return ref

    monkeypatch.setattr(firestore, "get_db", lambda: DB())
    firestore.ping()
    assert ref.ops == [("set", True), ("get",)]
