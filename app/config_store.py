"""Persistent dashboard settings."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = {
    "poll_interval_sec": 1,
    "telegram_realtime": True,
    "account_refresh_sec": 15,
    "mt5_base_url": "http://15.135.71.95:8080",
    "mt5_api_key": "alphafx",
    "mt5_symbol": "XAUUSD.pr",
    "mt5_trade_comment": "ABD",
    "volume": 0.1,
    "reward_risk_ratio": 2.0,
    "prefer_signal_tp": False,
    "auto_trade": False,
    "allow_trade_without_sl": False,
    "default_sl_points": 500,
    "telegram_fetch_limit": 100,
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


def load_config() -> dict:
    with _lock:
        _ensure_dir()
        if not _path.exists():
            return deepcopy(DEFAULTS)
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
        return merged


def save_config(updates: dict) -> dict:
    with _lock:
        cfg = load_config()
        for key, val in updates.items():
            if key in DEFAULTS:
                cfg[key] = val
        _ensure_dir()
        saved_at = datetime.now(timezone.utc).isoformat()
        cfg["config_saved_at"] = saved_at
        _path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg
