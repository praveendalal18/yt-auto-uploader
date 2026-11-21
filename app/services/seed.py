"""The 4 expected channels and their defaults, read from config.yaml (the CLI's settings file)."""
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import AIProfile, Channel, ChannelDefaults, default_slot_rules

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ["#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4d7c0f"]

# Same names/IDs the CLI uses (src/common.py CATEGORY_IDS).
CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals",
    "17": "Sports", "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News & Politics", "26": "Howto & Style", "27": "Education",
    "28": "Science & Technology", "29": "Nonprofits & Activism",
}
_CATEGORY_BY_NAME = {v.lower(): k for k, v in CATEGORIES.items()}


def norm_handle(handle: str) -> str:
    return (handle or "").strip().lower().lstrip("@")


@dataclass(frozen=True)
class ExpectedChannel:
    name: str
    handle: str
    colour: str
    defaults: ChannelDefaults

    def new_channel(self, channel_id: str, title: str, handle: str) -> Channel:
        return Channel(
            id=channel_id, title=title or self.name, handle=handle or self.handle, colour=self.colour,
            defaults=self.defaults.model_copy(deep=True), slot_rules=default_slot_rules(),
            ai_profile=AIProfile(language=self.defaults.language, kids_safe=self.defaults.made_for_kids),
        )


def load_expected(path: str | Path | None = None) -> list[ExpectedChannel]:
    path = path or os.environ.get("CONFIG_FILE") or ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    out = []
    for i, ch in enumerate(cfg.get("channels") or []):
        category = str(ch.get("category") or "People & Blogs")
        out.append(ExpectedChannel(
            name=ch["name"],
            handle=ch.get("handle", ""),
            colour=PALETTE[i % len(PALETTE)],
            defaults=ChannelDefaults(
                made_for_kids=bool(ch.get("made_for_kids", False)),
                ai_content=bool(ch.get("ai_content", False)),
                category_id=category if category.isdigit() else _CATEGORY_BY_NAME.get(category.lower(), "22"),
                language=ch.get("language") or "en",
                notify_subscribers=bool(ch.get("notify_subscribers", True)),
            ),
        ))
    return out


def match_expected(expected: list[ExpectedChannel], handle: str) -> ExpectedChannel | None:
    want = norm_handle(handle)
    return next((e for e in expected if want and norm_handle(e.handle) == want), None)


def generic_channel(channel_id: str, title: str, handle: str, index: int) -> Channel:
    return Channel(id=channel_id, title=title, handle=handle, colour=PALETTE[index % len(PALETTE)])
