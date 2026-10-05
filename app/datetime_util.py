"""Display timestamps in IST."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def format_message_time_ist(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    local = dt.astimezone(IST)
    return local.strftime("%Y-%m-%d %I:%M:%S %p IST")


def format_card_time_ist(iso: str | None) -> str | None:
    """Dashboard cards: dd/mm/yyyy hh:mm:ss AM/PM IST."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(IST)
    return local.strftime("%d/%m/%Y %I:%M:%S %p IST")


def enrich_date_ist(row: dict) -> dict:
    if row.get("date_ist"):
        return row
    raw = row.get("date")
    if not raw:
        return row
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return row
    return {**row, "date_ist": format_message_time_ist(dt)}
