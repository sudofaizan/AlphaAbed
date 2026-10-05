"""USD red-folder calendar from MT5 VPS + in-memory cache."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.datetime_util import format_card_time_ist
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig

log = logging.getLogger("alphaabed.news")

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "events": [],
    "fetched_at": None,
    "error": None,
    "ok": False,
}


def _client_from_cfg(cfg: dict) -> AlphaFxClient:
    return AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg.get("mt5_symbol") or "XAUUSD.pr",
            timeout=15,
        )
    )


def _enrich_event(ev: dict[str, Any]) -> dict[str, Any]:
    out = dict(ev)
    out["time_ist"] = format_card_time_ist(ev.get("time"))
    return out


def refresh_news_sync(cfg: dict) -> dict[str, Any]:
    """Fetch High-impact USD events from AlphaFX getUpcomingNews."""
    hours = int(cfg.get("news_hours_ahead") or 72)
    impact = (cfg.get("news_impact") or "High").strip() or "High"
    currency = (cfg.get("news_currency") or "USD").strip() or "USD"

    resp = _client_from_cfg(cfg).get_upcoming_news(
        hours=hours, impact=impact, currency=currency
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    with _lock:
        if resp.get("ok"):
            events = [_enrich_event(e) for e in (resp.get("events") or [])]
            _cache["events"] = events
            _cache["fetched_at"] = now_iso
            _cache["error"] = None
            _cache["ok"] = True
            _cache["count"] = len(events)
        else:
            _cache["error"] = resp.get("error") or "news fetch failed"
            _cache["ok"] = False
            _cache["fetched_at"] = now_iso
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
        return list(_cache.get("events") or [])
