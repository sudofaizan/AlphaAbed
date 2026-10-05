"""Background Telegram (realtime + optional backup poll) and account refresh."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.async_io import run_blocking
from app.config_store import load_config
from app.state import state
from app.telegram_service import (
    fetch_and_classify,
    poll_new_messages,
    run_realtime_listener,
)
from app.connectivity import record_mt5, record_telegram
from app.execution_tags import summarize_trade_execution
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
    health = await run_blocking(client.account_health)
    ok = bool(health.get("ok"))
    err = health.get("error") if not ok else None
    record_mt5(ok, err, health if ok else None)


async def _handle_row(row: dict, cfg: dict) -> None:
    trade = await process_signal_row(row, cfg)
    if trade and trade.get("action") != "skipped":
        row["execution"] = summarize_trade_execution(trade, cfg)
    kinds = cfg.get("signal_kinds_history") or []
    with state.lock:
        if row["kind"] in kinds:
            state.signal_history.insert(0, row)
            state.signal_history = state.signal_history[:200]
        state.last_message_id = max(state.last_message_id, int(row["message_id"]))
    if trade:
        state.push_event("trade", str(trade), trade=trade)
    state.push_event("signal", row.get("summary", ""), row=row)


async def worker_loop(stop_event: asyncio.Event) -> None:
    state.worker_running = True
    log.info("Worker started")

    listener_task: asyncio.Task | None = None

    async def on_row(row: dict, cfg: dict) -> None:
        await _handle_row(row, cfg)
        with state.lock:
            state.last_poll_at = datetime.now(timezone.utc).isoformat()
        record_telegram(True, None)

    while not stop_event.is_set():
        cfg = load_config()
        realtime = bool(cfg.get("telegram_realtime", True))
        poll_sec = max(1, int(cfg.get("poll_interval_sec", 1)))
        acct_sec = max(1, int(cfg.get("account_refresh_sec", 15)))

        if realtime and (listener_task is None or listener_task.done()):
            log.info("Starting Telegram realtime listener (instant new messages)")
            listener_task = asyncio.create_task(run_realtime_listener(stop_event, on_row))

        try:
            if not realtime:
                await poll_new_messages(cfg, state.last_message_id, on_row)
            await refresh_account_metrics(cfg)
            with state.lock:
                state.last_poll_at = datetime.now(timezone.utc).isoformat()
            if not realtime:
                record_telegram(True, None)
        except Exception as e:
            log.exception("Worker cycle error")
            record_telegram(False, str(e))

        wait = poll_sec if not realtime else acct_sec
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass

    if listener_task and not listener_task.done():
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
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
