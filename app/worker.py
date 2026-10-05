"""Background Telegram poll loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config_store import load_config
from app.state import state
from app.telegram_service import fetch_and_classify, poll_new_messages
from app.trading import process_signal_row
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig

log = logging.getLogger("alphaabed.worker")


async def refresh_account_metrics(cfg: dict) -> None:
    client = AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )
    health = client.account_health()
    with state.lock:
        state.last_mt5_ok = bool(health.get("ok"))
        if health.get("ok"):
            today = health.get("today") or {}
            state.today_pnl = today.get("closed_pl")
            state.account_equity = health.get("equity")


async def worker_loop(stop_event: asyncio.Event) -> None:
    state.worker_running = True
    log.info("Worker started")
    while not stop_event.is_set():
        cfg = load_config()
        interval = max(5, int(cfg.get("poll_interval_sec", 30)))
        try:
            async def on_signal(row, c):
                trade = await process_signal_row(row, c)
                with state.lock:
                    if row["kind"] in (c.get("signal_kinds_history") or []):
                        state.signal_history.insert(0, row)
                        state.signal_history = state.signal_history[:200]
                if trade:
                    state.push_event("trade", str(trade), trade=trade)
                state.push_event("signal", row.get("summary", ""), row=row)

            new_max = await poll_new_messages(cfg, state.last_message_id, on_signal)
            with state.lock:
                state.last_message_id = max(state.last_message_id, new_max)
            await refresh_account_metrics(cfg)
            with state.lock:
                state.last_poll_at = datetime.now(timezone.utc).isoformat()
                state.last_telegram_ok = True
                state.last_telegram_error = None
        except Exception as e:
            log.exception("Poll error")
            with state.lock:
                state.last_telegram_ok = False
                state.last_telegram_error = str(e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    state.worker_running = False


async def refresh_history_once() -> dict:
    cfg = load_config()
    limit = int(cfg.get("telegram_fetch_limit", 100))
    result = await fetch_and_classify(limit, cfg)
    if result.get("ok"):
        with state.lock:
            state.signal_history = result.get("signals", [])
            if state.signal_history:
                state.last_message_id = max(
                    state.last_message_id,
                    max(s["message_id"] for s in state.signal_history),
                )
    await refresh_account_metrics(cfg)
    return result
