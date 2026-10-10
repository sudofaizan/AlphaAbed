"""Persistent dashboard settings."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.mt5_accounts import normalize_mt5_accounts

DEFAULTS = {
    "poll_interval_sec": 1,
    "telegram_enabled": True,
    "telegram_realtime": True,
    "whatsapp_enabled": False,
    "whatsapp_messages_url": "",
    "whatsapp_poll_sec": 1,
    "account_refresh_sec": 15,
    "mt5_base_url": "http://15.135.71.95:8080",
    "mt5_api_key": "alphafx",
    "mt5_symbol": "XAUUSD.pr",
    "mt5_trade_comment": "ABD",
    "whatsapp_trade_comment": "WASIG",
    "volume": 0.1,
    "lot_mode": "fixed",
    "risk_usd": 30.0,
    "mt5_accounts": [],
    "reward_risk_ratio": 2.0,
    "prefer_signal_tp": False,
    "auto_trade": False,
    "allow_trade_without_sl": False,
    "default_sl_points": 500,
    "telegram_fetch_limit": 100,
    "trade_mt5": True,
    "capiffy_enabled": False,
    "trade_capiffy": False,
    "capiffy_volume": 0.01,
    "capiffy_symbol": "XAUUSD",
    "capiffy_account_id": "",
    "news_calendar_enabled": True,
    "news_hours_ahead": 72,
    "news_impact": "High",
    "news_display_impacts": "High,Medium,Low",
    "news_currency": "USD",
    "news_refresh_sec": 300,
    "capiffy_news_blackout": True,
    "capiffy_news_minutes_before": 30,
    "capiffy_news_minutes_after": 30,
    "signal_kinds_history": [
        "open_signal",
        "close_all",
        "partial_close",
        "incomplete_signal",
        "sl_fragment",
    ],
}

_lock = threading.Lock()
_path = Path(os.getenv("ALPHAABED_DATA_DIR", "data")) / "config.json"


def _ensure_dir() -> None:
    _path.parent.mkdir(parents=True, exist_ok=True)


def _load_config_unlocked() -> dict:
    _ensure_dir()
    if not _path.exists():
        return normalize_mt5_accounts(deepcopy(DEFAULTS))
    try:
        data = json.loads(_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULTS)
    merged = deepcopy(DEFAULTS)
    merged.update(data)
    if "config_saved_at" not in merged and _path.exists():
        try:
            merged["config_saved_at"] = datetime.fromtimestamp(
                _path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            pass
    return normalize_mt5_accounts(merged)


def load_config() -> dict:
    with _lock:
        return _load_config_unlocked()


def save_config(updates: dict) -> dict:
    with _lock:
        cfg = _load_config_unlocked()
        for key, val in updates.items():
            if key in DEFAULTS:
                cfg[key] = val
        cfg = normalize_mt5_accounts(cfg)
        saved_at = datetime.now(timezone.utc).isoformat()
        cfg["config_saved_at"] = saved_at
        _path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg
