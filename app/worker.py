"""Background Telegram, WhatsApp, and account refresh."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.async_io import run_blocking
from app.automation_pause import automation_paused, maybe_auto_unpause
from app.config_store import load_config
from app.state import state
from app.telegram_service import (
    fetch_and_classify,
    poll_new_messages,
    run_realtime_listener,
)
from app.connectivity import record_mt5, record_telegram, record_whatsapp
from app.execution_tags import summarize_trade_execution
from app.trading import process_signal_row
from app.mt5_accounts import primary_mt5_client
from app.signal_history import (
    enrich_row_trade_plan,
    merge_signal_histories,
    should_show_in_history,
    upsert_history,
)
from app.whatsapp_service import fetch_whatsapp_history_rows, poll_new_whatsapp_messages

log = logging.getLogger("alphaabed.worker")

PAUSE_POLL_SEC = 30


async def _sleep_or_stop(stop_event: asyncio.Event, sec: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=sec)
    except asyncio.TimeoutError:
        pass


async def _reload_cfg_unpause() -> dict:
    return await run_blocking(maybe_auto_unpause)


async def refresh_account_metrics(cfg: dict) -> None:
    client = primary_mt5_client(cfg)
    health = await run_blocking(client.account_health)
    ok = bool(health.get("ok"))
    err = health.get("error") if not ok else None
    record_mt5(ok, err, health if ok else None)


async def _handle_row(row: dict, cfg: dict) -> None:
    trade = await process_signal_row(row, cfg)
    if trade and trade.get("action") in ("open", "close_all", "partial_close"):
        row["execution"] = summarize_trade_execution(trade, cfg)
    elif trade and trade.get("action") == "skipped" and trade.get("reason") == "auto_trade disabled":
        row["history_note"] = "Not traded — auto-trade off"
    if should_show_in_history(row, cfg):
        await run_blocking(enrich_row_trade_plan, row, cfg)
    with state.lock:
        if should_show_in_history(row, cfg):
            state.signal_history = upsert_history(state.signal_history, row)
        if row.get("source") == "whatsapp":
            state.last_whatsapp_message_id = str(row.get("message_id") or "")
        else:
            try:
                state.last_message_id = max(
                    state.last_message_id, int(row.get("message_id") or 0)
                )
            except (TypeError, ValueError):
                pass
    if trade:
        state.push_event("trade", str(trade), trade=trade)
    state.push_event("signal", row.get("summary", ""), row=row)


async def _cancel_listener(listener_task: asyncio.Task | None) -> None:
    if listener_task and not listener_task.done():
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass


async def whatsapp_poll_loop(stop_event: asyncio.Event) -> None:
    log.info("WhatsApp poll loop started")
    bootstrapped = False
    while not stop_event.is_set():
        cfg = await _reload_cfg_unpause()
        sec = max(1, int(cfg.get("whatsapp_poll_sec") or 1))
        if automation_paused(cfg):
            await _sleep_or_stop(stop_event, PAUSE_POLL_SEC)
            continue
        if not cfg.get("whatsapp_enabled") or not (cfg.get("whatsapp_messages_url") or "").strip():
            await _sleep_or_stop(stop_event, sec)
            continue
        try:
            if not bootstrapped:
                await run_blocking(poll_new_whatsapp_messages, cfg, bootstrap=True)
                wa_hist = await run_blocking(fetch_whatsapp_history_rows, cfg)
                for row in wa_hist:
                    await run_blocking(enrich_row_trade_plan, row, cfg)
                with state.lock:
                    state.signal_history = merge_signal_histories(state.signal_history, wa_hist)
                bootstrapped = True
            result = await run_blocking(poll_new_whatsapp_messages, cfg)
            if result.get("ok"):
                record_whatsapp(True, None, result.get("channel"))
                for row in result.get("rows") or []:
                    await _handle_row(row, load_config())
            else:
                record_whatsapp(False, result.get("error"))
        except Exception as exc:
            log.exception("WhatsApp poll error")
            record_whatsapp(False, str(exc))
        await _sleep_or_stop(stop_event, sec)


async def worker_loop(stop_event: asyncio.Event) -> None:
    state.worker_running = True
    log.info("Worker started")

    listener_task: asyncio.Task | None = None
    wa_task = asyncio.create_task(whatsapp_poll_loop(stop_event))

    async def on_row(row: dict, cfg: dict) -> None:
        if automation_paused(cfg):
            return
        if not cfg.get("telegram_enabled", True):
            return
        await _handle_row(row, cfg)
        with state.lock:
            state.last_poll_at = datetime.now(timezone.utc).isoformat()
        record_telegram(True, None)

    while not stop_event.is_set():
        cfg = await _reload_cfg_unpause()
        if automation_paused(cfg):
            await _cancel_listener(listener_task)
            listener_task = None
            with state.lock:
                state.last_poll_at = datetime.now(timezone.utc).isoformat()
            log.debug("Automation paused — skipping Telegram / account polls")
            await _sleep_or_stop(stop_event, PAUSE_POLL_SEC)
            continue

        realtime = bool(cfg.get("telegram_realtime", True))
        poll_sec = max(1, int(cfg.get("poll_interval_sec", 1)))
        acct_sec = max(1, int(cfg.get("account_refresh_sec", 15)))

        if cfg.get("telegram_enabled", True) and realtime and (
            listener_task is None or listener_task.done()
        ):
            log.info("Starting Telegram realtime listener (instant new messages)")
            listener_task = asyncio.create_task(run_realtime_listener(stop_event, on_row))

        try:
            if cfg.get("telegram_enabled", True) and not realtime:
                await poll_new_messages(cfg, state.last_message_id, on_row)
            await refresh_account_metrics(cfg)
            with state.lock:
                state.last_poll_at = datetime.now(timezone.utc).isoformat()
            if cfg.get("telegram_enabled", True) and not realtime:
                record_telegram(True, None)
        except Exception as e:
            log.exception("Worker cycle error")
            record_telegram(False, str(e))

        wait = poll_sec if (cfg.get("telegram_enabled", True) and not realtime) else acct_sec
        await _sleep_or_stop(stop_event, wait)

    await _cancel_listener(listener_task)
    wa_task.cancel()
    try:
        await wa_task
    except asyncio.CancelledError:
        pass
    state.worker_running = False


async def refresh_history_once() -> dict:
    cfg = await _reload_cfg_unpause()
    if automation_paused(cfg):
        return {"ok": False, "skipped": True, "reason": "automation paused"}
    limit = int(cfg.get("telegram_fetch_limit", 100))
    result = await fetch_and_classify(limit, cfg)
    tg_signals = result.get("signals", []) if result.get("ok") else []
    wa_signals: list = []
    if (cfg.get("whatsapp_messages_url") or "").strip():
        wa_signals = await run_blocking(fetch_whatsapp_history_rows, cfg)
        for row in wa_signals:
            await run_blocking(enrich_row_trade_plan, row, cfg)
    with state.lock:
        state.signal_history = merge_signal_histories(tg_signals, wa_signals)
        tg_ids = [
            int(s["message_id"])
            for s in state.signal_history
            if s.get("source") != "whatsapp"
            and str(s.get("message_id", "")).isdigit()
        ]
        if tg_ids:
            state.last_message_id = max(state.last_message_id, max(tg_ids))
    await refresh_account_metrics(cfg)
    result["signal_count"] = len(state.signal_history)
    result["whatsapp_history_count"] = len(wa_signals)
    return result
