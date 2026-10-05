"""Runtime state shared by API and background worker."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_poll_at: str | None = None
    last_telegram_ok: bool | None = None
    last_telegram_error: str | None = None
    last_telegram_ok_at: str | None = None
    last_mt5_ok: bool | None = None
    last_mt5_error: str | None = None
    last_mt5_ok_at: str | None = None
    last_capiffy_ok: bool | None = None
    last_capiffy_error: str | None = None
    last_capiffy_ok_at: str | None = None
    today_pnl: float | None = None
    account_equity: float | None = None
    signal_history: list[dict[str, Any]] = field(default_factory=list)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    last_message_id: int = 0
    worker_running: bool = False

    def push_event(self, kind: str, message: str, **extra: Any) -> None:
        with self.lock:
            self.recent_events.insert(
                0,
                {"kind": kind, "message": message, **extra},
            )
            self.recent_events = self.recent_events[:50]


state = RuntimeState()
