"""Data access. FirestoreRepo in production; MemoryRepo for tests."""
from collections.abc import Callable

from app.models import AppSettings, Channel
from app.timeutil import now_utc


class FirestoreRepo:
    def __init__(self, db_factory: Callable):
        self._db_factory = db_factory  # called lazily so the app starts without touching Google

    @property
    def db(self):
        return self._db_factory()

    def list_channels(self) -> list[Channel]:
        chans = [Channel.model_validate(d.to_dict() | {"id": d.id}) for d in self.db.collection("channels").stream()]
        return sorted(chans, key=lambda c: c.title.lower())

    def get_channel(self, channel_id: str) -> Channel | None:
        snap = self.db.collection("channels").document(channel_id).get()
        return Channel.model_validate(snap.to_dict() | {"id": snap.id}) if snap.exists else None

    def save_channel(self, channel: Channel) -> None:
        channel.updated_at = now_utc()
        self.db.collection("channels").document(channel.id).set(channel.model_dump(exclude={"id"}))

    def get_app_settings(self) -> AppSettings:
        snap = self.db.collection("settings").document("app").get()
        return AppSettings.model_validate(snap.to_dict()) if snap.exists else AppSettings()

    def save_app_settings(self, s: AppSettings) -> None:
        s.updated_at = now_utc()
        self.db.collection("settings").document("app").set(s.model_dump())


class MemoryRepo:
    def __init__(self):
        self.channels: dict[str, dict] = {}
        self.app_settings: dict | None = None

    def list_channels(self) -> list[Channel]:
        return sorted((Channel.model_validate(d) for d in self.channels.values()), key=lambda c: c.title.lower())

    def get_channel(self, channel_id: str) -> Channel | None:
        d = self.channels.get(channel_id)
        return Channel.model_validate(d) if d else None

    def save_channel(self, channel: Channel) -> None:
        channel.updated_at = now_utc()
        self.channels[channel.id] = channel.model_dump()

    def get_app_settings(self) -> AppSettings:
        return AppSettings.model_validate(self.app_settings) if self.app_settings else AppSettings()

    def save_app_settings(self, s: AppSettings) -> None:
        s.updated_at = now_utc()
        self.app_settings = s.model_dump()
