"""Store UTC, display Asia/Kolkata: 'Sun 30 Nov, 7:00 PM'."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(UTC)


def fmt_ist(dt: datetime | None, with_year: bool = False) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:  # treat naive values as UTC
        dt = dt.replace(tzinfo=UTC)
    local = dt.astimezone(IST)
    hour = local.strftime("%I").lstrip("0") or "12"
    date = f"{local:%a} {local.day} {local:%b}" + (f" {local.year}" if with_year else "")
    return f"{date}, {hour}:{local:%M} {local:%p}"
