"""Process new Telegram messages: classify, merge SL fragments, optional MT5."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from signals.classify import ParsedMessage, TradeSignal, classify_text, format_signal_line, merge_sl_fragment
from signals.mt5_api import dispatch_signal

log = logging.getLogger("alphaabed")


@dataclass
class SignalHandler:
    pending: TradeSignal | None = None
    pending_at: float = 0.0
    pending_msg_id: int | None = None
    fragment_window_sec: int = field(
        default_factory=lambda: int(os.getenv("SL_FRAGMENT_WINDOW_SEC", "180"))
    )
    dry_run: bool = field(
        default_factory=lambda: os.getenv("MT5_DRY_RUN", "true").lower() != "false"
    )
    auto_trade: bool = field(
        default_factory=lambda: os.getenv("MT5_AUTO_TRADE", "false").lower() == "true"
    )

    def _clear_pending(self) -> None:
        self.pending = None
        self.pending_at = 0.0
        self.pending_msg_id = None

    def _remember_pending(self, signal: TradeSignal, message_id: int) -> None:
        self.pending = signal
        self.pending_at = time.time()
        self.pending_msg_id = message_id

    def _pending_expired(self) -> bool:
        if not self.pending:
            return True
        return (time.time() - self.pending_at) > self.fragment_window_sec

    async def handle(self, text: str, message_id: int) -> ParsedMessage:
        parsed = classify_text(text)

        if parsed.kind == "sl_fragment" and parsed.signal and self.pending and not self._pending_expired():
            merged = merge_sl_fragment(self.pending, text)
            if merged and merged.sl is not None:
                log.info(
                    "Merged SL into pending signal from msg %s: %s",
                    self.pending_msg_id,
                    format_signal_line(
                        ParsedMessage(kind="open_signal", signal=merged),
                        message_id,
                    ),
                )
                self._clear_pending()
                if self.auto_trade:
                    dispatch_signal("open_signal", merged, message_id=message_id, dry_run=self.dry_run)
                parsed = ParsedMessage(kind="open_signal", signal=merged, reason="merged SL fragment")
                return parsed

        if parsed.kind == "incomplete_signal" and parsed.signal and parsed.signal.sl is None:
            self._remember_pending(parsed.signal, message_id)
            log.info(
                "Waiting for SL fragment (within %ss): %s",
                self.fragment_window_sec,
                parsed.raw_text.replace("\n", " ")[:120],
            )
            return parsed

        if self._pending_expired():
            self._clear_pending()

        if parsed.kind in ("promo", "commentary", "unknown"):
            log.debug("Ignored [%s]: %s", parsed.kind, text[:80])
            return parsed

        log.info(
            "Classified msg %s: %s",
            message_id,
            format_signal_line(parsed, message_id),
        )

        if self.auto_trade and parsed.kind in ("open_signal", "close_all", "partial_close"):
            dispatch_signal(parsed.kind, parsed.signal, message_id=message_id, dry_run=self.dry_run)

        return parsed
