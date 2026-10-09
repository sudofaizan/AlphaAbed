"""USD red-folder calendar from MT5 VPS + in-memory cache."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.datetime_util import format_card_time_ist
from app.mt5_accounts import primary_mt5_client

log = logging.getLogger("alphaabed.news")

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "events": [],
    "fetched_at": None,
    "error": None,
    "ok": False,
}


def _client_from_cfg(cfg: dict):
    return primary_mt5_client(cfg)


def _parse_time_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _enrich_event(ev: dict[str, Any]) -> dict[str, Any]:
    out = dict(ev)
    out["time_ist"] = format_card_time_ist(ev.get("time"))
    if out.get("minutes_until") is None:
        start = _parse_time_utc(ev.get("time"))
        if start:
            out["minutes_until"] = max(0, int((start - datetime.now(timezone.utc)).total_seconds() // 60))
    return out


def _display_impacts(cfg: dict) -> list[str]:
    raw = (cfg.get("news_display_impacts") or "High,Medium,Low").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["High", "Medium", "Low"]


def _fetch_upcoming_merged(cfg: dict) -> tuple[list[dict[str, Any]], str | None]:
    """Merge calendar rows for dashboard (several impact API calls)."""
    hours = int(cfg.get("news_hours_ahead") or 72)
    currency = (cfg.get("news_currency") or "USD").strip() or "USD"
    client = _client_from_cfg(cfg)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_err: str | None = None
    any_ok = False

    for impact in _display_impacts(cfg):
        resp = client.get_upcoming_news(hours=hours, impact=impact, currency=currency)
        if resp.get("ok"):
            any_ok = True
            for e in resp.get("events") or []:
                eid = str(e.get("event_id") or f"{e.get('time')}|{e.get('title')}")
                if eid in seen:
                    continue
                seen.add(eid)
                merged.append(_enrich_event(e))
        else:
            last_err = resp.get("error") or last_err

    merged.sort(key=lambda e: e.get("time") or "")
    if not any_ok:
        return [], last_err or "news fetch failed"
    return merged, None


def events_matching_blackout_impact(cfg: dict, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Capiffy blackout uses news_impact only (default High)."""
    want = (cfg.get("news_impact") or "High").strip().lower()
    if not want:
        return list(events)
    return [e for e in events if (e.get("impact") or "").strip().lower() == want]


def refresh_news_sync(cfg: dict) -> dict[str, Any]:
    """Fetch upcoming USD calendar from AlphaFX getUpcomingNews (multi-impact for UI)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    events, err = _fetch_upcoming_merged(cfg)
    with _lock:
        if err:
            _cache["error"] = err
            _cache["ok"] = False
            _cache["fetched_at"] = now_iso
        else:
            _cache["events"] = events
            _cache["fetched_at"] = now_iso
            _cache["error"] = None
            _cache["ok"] = True
            _cache["count"] = len(events)
        return snapshot_unlocked()


def snapshot_unlocked() -> dict[str, Any]:
    return {
        "ok": _cache.get("ok", False),
        "events": list(_cache.get("events") or []),
        "count": len(_cache.get("events") or []),
        "fetched_at": _cache.get("fetched_at"),
        "fetched_at_ist": format_card_time_ist(_cache.get("fetched_at")),
        "error": _cache.get("error"),
    }


def get_news_snapshot(cfg: dict) -> dict[str, Any]:
    refresh_sec = int(cfg.get("news_refresh_sec") or 300)
    with _lock:
        fetched = _cache.get("fetched_at")
        stale = True
        if fetched:
            try:
                dt = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
                stale = age >= refresh_sec
            except ValueError:
                stale = True
        if stale or not _cache.get("events"):
            pass
        else:
            return snapshot_unlocked()

    return refresh_news_sync(cfg)


def maybe_refresh_news(cfg: dict) -> None:
    """Background refresh if cache is stale."""
    refresh_sec = int(cfg.get("news_refresh_sec") or 300)
    with _lock:
        fetched = _cache.get("fetched_at")
        if fetched:
            try:
                dt = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
                age = time.time() - dt.timestamp()
                if age < refresh_sec:
                    return
            except ValueError:
                pass
    try:
        refresh_news_sync(cfg)
    except Exception as exc:
        log.warning("News refresh failed: %s", exc)


def cached_events_for_blackout(cfg: dict) -> list[dict[str, Any]]:
    if not cfg.get("news_calendar_enabled", True):
        return []
    with _lock:
        all_ev = list(_cache.get("events") or [])
    return events_matching_blackout_impact(cfg, all_ev)
