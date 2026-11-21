"""Pydantic models for Firestore documents (see docs/SPEC.md §4)."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # index = Python weekday()
TokenStatus = Literal["ok", "expired", "revoked"]

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class SlotRule(BaseModel):
    type: Literal["Short", "Long"]
    weekdays: list[int] = Field(default_factory=list)  # 0 = Monday … 6 = Sunday
    time: str = "19:00"  # HH:MM, Asia/Kolkata

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekdays must be 0 (Mon) to 6 (Sun)")
        return sorted(set(v))

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        v = v.strip()
        if not _TIME.match(v):
            raise ValueError("time must look like 19:00 (24-hour clock)")
        return v


def default_slot_rules() -> list[SlotRule]:
    return [SlotRule(type="Short", weekdays=[0, 1, 2, 3, 4, 5], time="19:00"),
            SlotRule(type="Long", weekdays=[6], time="19:00")]


class ChannelDefaults(BaseModel):
    made_for_kids: bool = False
    ai_content: bool = False
    category_id: str = "22"  # People & Blogs
    language: str = "en"
    notify_subscribers: bool = True
    default_playlist: str = Field(default="", max_length=150)

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        v = v.strip()
        if not _LANG.match(v):
            raise ValueError("language must be a code like en, hi or en-IN")
        return v


class AIProfile(BaseModel):
    audience: str = Field(default="", max_length=500)
    tone: str = Field(default="", max_length=300)
    language: str = "en"
    title_style: str = Field(default="", max_length=500)
    hashtags: list[str] = Field(default_factory=list)
    banned_words: list[str] = Field(default_factory=list)
    kids_safe: bool = False

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = t.strip().lstrip("#")
            if not t:
                continue
            if not re.fullmatch(r"\w{1,50}", t):
                raise ValueError(f"hashtag '#{t}' can only use letters, numbers and _")
            if f"#{t}" not in out:
                out.append(f"#{t}")
        if len(out) > 15:
            raise ValueError("use at most 15 hashtags")
        return out

    @field_validator("banned_words")
    @classmethod
    def _banned(cls, v: list[str]) -> list[str]:
        return [w.strip() for w in v if w.strip()][:100]


class Channel(BaseModel):
    id: str  # YouTube channel ID (UC…)
    title: str
    handle: str = ""
    colour: str = "#64748b"
    thumbnail_url: str = ""
    connected: bool = False
    token_enc: str | None = None  # Fernet-encrypted {"refresh_token", "scopes"}
    token_status: TokenStatus = "ok"
    token_error: str = ""
    token_checked_at: datetime | None = None
    defaults: ChannelDefaults = Field(default_factory=ChannelDefaults)
    slot_rules: list[SlotRule] = Field(default_factory=default_slot_rules)
    ai_profile: AIProfile = Field(default_factory=AIProfile)
    playlists_cache: dict[str, str] = Field(default_factory=dict)
    connected_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("colour")
    @classmethod
    def _colour(cls, v: str) -> str:
        if not _COLOUR.match(v):
            raise ValueError("colour must look like #2563eb")
        return v.lower()

    @model_validator(mode="after")
    def _kids(self) -> "Channel":
        # Made-for-kids channels always get the COPPA-safe AI rules.
        if self.defaults.made_for_kids:
            self.ai_profile.kids_safe = True
        return self

    @property
    def healthy(self) -> bool:
        return self.connected and self.token_status == "ok"


class AppSettings(BaseModel):
    notify_email: str = ""
    sheet_id: str = ""
    sheet_sync: bool = False
    timezone: str = "Asia/Kolkata"
    audit_approved: bool = False
    account_token_enc: str | None = None  # Fernet-encrypted token for Sheets + Gmail
    account_email: str = ""
    account_status: TokenStatus | Literal["missing"] = "missing"
    account_error: str = ""
    account_checked_at: datetime | None = None
    updated_at: datetime | None = None
