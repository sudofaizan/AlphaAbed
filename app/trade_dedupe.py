"""Trade guards: per-message dedupe + global cooldown between auto-trades."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_path = Path(os.getenv("ALPHAABED_DATA_DIR", "data")) / "traded_signals.json"
_MAX = 5000


def _parse_utc(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def trade_key(source: str, message_id: object) -> str | None:
    if message_id is None:
        return None
    mid = str(message_id).strip()
    if not mid:
        return None
    src = (source or "telegram").lower().strip()
    return f"{src}:{mid}"


def _load_store_unlocked() -> dict:
    _path.parent.mkdir(parents=True, exist_ok=True)
    if not _path.exists():
        return {"keys": set(), "last_trade_at": None}
    try:
        data = json.loads(_path.read_text(encoding="utf-8"))
        keys = data.get("keys") or []
        return {
            "keys": set(str(x) for x in keys),
            "last_trade_at": data.get("last_trade_at"),
        }
    except (json.JSONDecodeError, OSError):
        return {"keys": set(), "last_trade_at": None}


def _save_store_unlocked(keys: set[str], last_trade_at: str | None) -> None:
    trimmed = list(keys)[-_MAX:]
    payload: dict = {"keys": trimmed}
    if last_trade_at:
        payload["last_trade_at"] = last_trade_at
    _path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def already_traded(source: str, message_id: object) -> bool:
    key = trade_key(source, message_id)
    if not key:
        return False
    with _lock:
        return key in _load_store_unlocked()["keys"]


def check_trade_cooldown(cooldown_sec: int) -> tuple[bool, str]:
    """Return (True, "") if a new auto-trade is allowed; else (False, reason)."""
    sec = int(cooldown_sec or 0)
    if sec <= 0:
        return True, ""
    now = datetime.now(timezone.utc)
    with _lock:
        store = _load_store_unlocked()
        last = _parse_utc(store.get("last_trade_at") or "")
    if not last:
        return True, ""
    elapsed = (now - last).total_seconds()
    if elapsed >= sec:
        return True, ""
    wait = int(sec - elapsed) + 1
    return False, f"trade cooldown ({sec}s) — ignored, ~{wait}s left"


def mark_trade_executed() -> None:
    """Start cooldown window after committing to an auto-trade."""
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        store = _load_store_unlocked()
        _save_store_unlocked(store["keys"], now)


def reserve_trade_execution(source: str, message_id: object) -> tuple[bool, str]:
    """
    Atomically claim this message for execution.
    Returns (True, "") if caller should proceed; (False, reason) if duplicate.
    """
    key = trade_key(source, message_id)
    if not key:
        return True, ""
    with _lock:
        store = _load_store_unlocked()
        keys = store["keys"]
        if key in keys:
            return False, "already executed for this message id"
        keys.add(key)
        _save_store_unlocked(keys, store.get("last_trade_at"))
    return True, ""
