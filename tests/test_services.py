"""Phase 2 service units: crypto, seed, repo, token checks, models."""
import pytest
from google.auth.exceptions import RefreshError, TransportError
from pydantic import ValidationError

from app.models import AppSettings, Channel, SlotRule
from app.services import tokens as token_service
from app.services.crypto import CipherNotConfigured, TokenCipher, TokenDecryptError
from app.services.repo import FirestoreRepo, MemoryRepo
from app.services.seed import load_expected, match_expected
from tests.conftest import FERNET_KEY

OTHER_KEY = "Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGw="


def test_cipher_roundtrip_and_tamper_detection():
    c = TokenCipher(FERNET_KEY)
    blob = c.encrypt({"refresh_token": "secret-value"})
    assert "secret-value" not in blob
    assert c.decrypt(blob) == {"refresh_token": "secret-value"}
    with pytest.raises(TokenDecryptError):
        TokenCipher(OTHER_KEY).decrypt(blob)
    with pytest.raises(TokenDecryptError):
        c.decrypt(blob[:-4] + "AAAA")


@pytest.mark.parametrize("key", ["", "not-a-key"])
def test_cipher_needs_a_valid_key(key):
    with pytest.raises(CipherNotConfigured, match="FERNET_KEY"):
        TokenCipher(key)


def test_seed_reads_the_four_channels_from_config():
    exp = load_expected()
    assert [e.handle for e in exp] == ["@InkandMotionYT", "@MirrorkinPress", "@KidzCuriousLabs", "@AIPraveen18"]
    assert [e.defaults.made_for_kids for e in exp] == [False, True, True, False]
    assert [e.defaults.category_id for e in exp] == ["1", "27", "27", "28"]
    assert len({e.colour for e in exp}) == 4
    assert match_expected(exp, "@inkandmotionyt").name == "Ink & Motion"
    assert match_expected(exp, "inkandmotionyt").name == "Ink & Motion"
    assert match_expected(exp, "") is None


def test_slot_rule_validation():
    assert SlotRule(type="Short", weekdays=[5, 1, 1], time=" 07:05 ").weekdays == [1, 5]
    for bad in ({"weekdays": [7]}, {"time": "24:00"}, {"time": "7:00"}):
        with pytest.raises(ValidationError):
            SlotRule(type="Short", **bad)


def test_kids_channel_always_kids_safe():
    ch = Channel(id="x", title="t", defaults={"made_for_kids": True}, ai_profile={"kids_safe": False})
    assert ch.ai_profile.kids_safe


# --- Firestore repo against a tiny fake client ------------------------------

class FakeSnap:
    def __init__(self, id, data):
        self.id, self._data = id, data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDoc:
    def __init__(self, store, id):
        self.store, self.id = store, id

    def get(self):
        return FakeSnap(self.id, self.store.get(self.id))

    def set(self, data):
        self.store[self.id] = data


class FakeCollection:
    def __init__(self, store):
        self.store = store

    def document(self, id):
        return FakeDoc(self.store, id)

    def stream(self):
        return [FakeSnap(k, v) for k, v in self.store.items()]


class FakeDB:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return FakeCollection(self.data.setdefault(name, {}))


def test_firestore_repo_roundtrip():
    db = FakeDB()
    repo = FirestoreRepo(lambda: db)
    assert repo.get_channel("UC1") is None and repo.list_channels() == []
    repo.save_channel(Channel(id="UC1", title="b"))
    repo.save_channel(Channel(id="UC2", title="A"))
    assert "id" not in db.data["channels"]["UC1"]  # id is the document key
    assert [c.id for c in repo.list_channels()] == ["UC2", "UC1"]
    assert repo.get_channel("UC1").updated_at is not None
    assert repo.get_app_settings() == AppSettings()
    repo.save_app_settings(AppSettings(sheet_id="abc"))
    assert repo.get_app_settings().sheet_id == "abc"


# --- token checks -------------------------------------------------------------

@pytest.mark.parametrize("exc, expected", [
    (None, "ok"),
    (RefreshError("invalid_grant: Token has been expired or revoked."), "expired"),
])
def test_check_token(monkeypatch, exc, expected):
    def refresh(self, request):
        if exc:
            raise exc

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", refresh)
    assert token_service.check_token({"refresh_token": "r", "scopes": []}, "id", "secret") == expected


@pytest.mark.parametrize("exc", [TransportError("dns"), RefreshError("internal_failure")])
def test_check_token_temporary_errors(monkeypatch, exc):
    def refresh(self, request):
        raise exc

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", refresh)
    with pytest.raises(token_service.TokenCheckError):
        token_service.check_token({"refresh_token": "r"}, "id", "secret")


def test_check_all_handles_undecryptable_token_and_account():
    repo, cipher = MemoryRepo(), TokenCipher(FERNET_KEY)
    repo.save_channel(Channel(id="UC1", title="One", connected=True, token_enc=TokenCipher(OTHER_KEY).encrypt({})))
    repo.save_channel(Channel(id="UC2", title="Never connected"))
    repo.save_app_settings(AppSettings(account_token_enc=cipher.encrypt({"refresh_token": "a"}),
                                       account_status="ok"))
    problems = token_service.check_all(repo, cipher, "id", "s", checker=lambda *_: "expired")
    assert repo.get_channel("UC1").token_status == "expired"
    assert "FERNET_KEY" in repo.get_channel("UC1").token_error
    assert repo.get_app_settings().account_status == "expired"
    assert len(problems) == 2
