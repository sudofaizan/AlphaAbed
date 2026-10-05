"""Block Capiffy opens around red-folder news (MT5 still allowed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.news_service import cached_events_for_blackout, get_news_snapshot


def _parse_event_time(iso: str | None) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def capiffy_news_blackout(
    cfg: dict,
    *,
    events: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """
    Returns (blocked, reason, matching_event).
    Block window: [event - before_min, event + after_min].
    """
    if not cfg.get("capiffy_news_blackout", True):
        return False, "", None
    if not cfg.get("capiffy_enabled") or not cfg.get("trade_capiffy"):
        return False, "", None

    before = int(cfg.get("capiffy_news_minutes_before") or 30)
    after = int(cfg.get("capiffy_news_minutes_after") or 30)
    evs = events if events is not None else cached_events_for_blackout(cfg)
    if not evs and cfg.get("news_calendar_enabled", True):
        snap = get_news_snapshot(cfg)
        evs = snap.get("events") or []

    now = datetime.now(timezone.utc)
    for ev in evs:
        start = _parse_event_time(ev.get("time"))
        if not start:
            continue
        win_start = start - timedelta(minutes=before)
        win_end = start + timedelta(minutes=after)
        if win_start <= now <= win_end:
            title = ev.get("title") or "Red-folder news"
            when = ev.get("time_ist") or ev.get("time") or ""
            reason = (
                f"Capiffy blocked: {title} ({when}) — "
                f"no opens {before}m before / {after}m after (prop rule)"
            )
            return True, reason, ev
    return False, "", None


def blackout_status(cfg: dict) -> dict[str, Any]:
    blocked, reason, ev = capiffy_news_blackout(cfg)
    return {
        "capiffy_blackout_active": blocked,
        "capiffy_blackout_reason": reason if blocked else None,
        "capiffy_blackout_event": ev,
    }
