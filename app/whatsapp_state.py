"""Persist seen WhatsApp message IDs (dedupe)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_path = Path(os.getenv("ALPHAABED_DATA_DIR", "data")) / "whatsapp_seen.json"
_MAX = 2000


def _load_unlocked() -> set[str]:
    _path.parent.mkdir(parents=True, exist_ok=True)
    if not _path.exists():
        return set()
    try:
        data = json.loads(_path.read_text(encoding="utf-8"))
        ids = data.get("seen_ids") or []
        return set(str(x) for x in ids)
    except (json.JSONDecodeError, OSError):
        return set()


def load_seen_ids() -> set[str]:
    with _lock:
        return _load_unlocked()


def mark_seen(message_id: str) -> None:
    if not message_id:
        return
    with _lock:
        seen = _load_unlocked()
        seen.add(str(message_id))
        trimmed = list(seen)[-_MAX:]
        _path.write_text(json.dumps({"seen_ids": trimmed}, indent=2), encoding="utf-8")


def mark_seen_many(message_ids: list[str]) -> None:
    with _lock:
        seen = _load_unlocked()
        for mid in message_ids:
            if mid:
                seen.add(str(mid))
        trimmed = list(seen)[-_MAX:]
        _path.write_text(json.dumps({"seen_ids": trimmed}, indent=2), encoding="utf-8")
