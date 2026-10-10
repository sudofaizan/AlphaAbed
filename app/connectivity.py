"""Background Telegram / MT5 / Capiffy connectivity checks (every ~60s)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.async_io import run_blocking
from app.config_store import load_config
from app.dual_trade import test_capiffy_connection, test_mt5_account
from app.mt5_accounts import list_enabled_mt5_accounts
from app.news_service import maybe_refresh_news
from app.state import state
from app.telegram_service import test_telegram
from app.whatsapp_service import test_whatsapp_feed

log = logging.getLogger("alphaabed.connectivity")

HEALTH_CHECK_SEC = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_telegram(ok: bool | None, error: str | None = None) -> None:
    with state.lock:
        state.last_telegram_ok = ok
        if ok is True:
            state.last_telegram_ok_at = _utc_now_iso()
            state.last_telegram_error = None
        elif ok is False and error is not None:
            state.last_telegram_error = error


def record_mt5(ok: bool, error: str | None = None, account: dict | None = None) -> None:
    with state.lock:
        state.last_mt5_ok = ok
        if ok:
            state.last_mt5_ok_at = _utc_now_iso()
            state.last_mt5_error = None
            if account and account.get("ok"):
                today = account.get("today") or {}
                state.today_pnl = today.get("closed_pl")
                state.account_equity = account.get("equity")
        elif error is not None:
            state.last_mt5_error = error


def record_whatsapp(ok: bool | None, error: str | None = None, channel: str | None = None) -> None:
    with state.lock:
        state.last_whatsapp_ok = ok
        if ok is True:
            state.last_whatsapp_ok_at = _utc_now_iso()
            state.last_whatsapp_error = None
        elif ok is False and error is not None:
            state.last_whatsapp_error = error


def record_capiffy(ok: bool | None, error: str | None = None) -> None:
    """ok=None means Capiffy disabled (card shows Off)."""
    with state.lock:
        state.last_capiffy_ok = ok
        if ok is True:
            state.last_capiffy_ok_at = _utc_now_iso()
            state.last_capiffy_error = None
        elif ok is False and error is not None:
            state.last_capiffy_error = error


async def check_mt5(cfg: dict) -> dict:
    accounts = list_enabled_mt5_accounts(cfg)
    if not accounts:
        record_mt5(False, "No MT5 accounts configured")
        return {"ok": False, "error": "No MT5 accounts configured"}

    results = []
    for acc in accounts:
        r = await run_blocking(test_mt5_account, acc)
        results.append(r)

    ok = all(r.get("ok") for r in results)
    err = None
    if not ok:
        failed = [r for r in results if not r.get("ok")]
        err = failed[0].get("error") or "MT5 check failed"
    primary = results[0]
    acct = primary.get("account") if primary.get("ok") else None
    record_mt5(ok, err, acct if isinstance(acct, dict) and acct.get("ok") else None)
    return {"ok": ok, "error": err, "accounts": results}


async def run_connectivity_checks(cfg: dict | None = None) -> None:
    cfg = cfg or load_config()

    if cfg.get("telegram_enabled", True):
        tg = await test_telegram()
        record_telegram(bool(tg.get("ok")), tg.get("error"))
    else:
        record_telegram(None, None)

    if cfg.get("whatsapp_enabled") and (cfg.get("whatsapp_messages_url") or "").strip():
        wa = await run_blocking(test_whatsapp_feed, cfg)
        record_whatsapp(bool(wa.get("ok")), wa.get("error"))
    else:
        record_whatsapp(None, None)

    await check_mt5(cfg)

    if cfg.get("capiffy_enabled"):
        cap = await run_blocking(test_capiffy_connection, cfg)
        record_capiffy(bool(cap.get("ok")), cap.get("error"))
    else:
        record_capiffy(None, None)

    if cfg.get("news_calendar_enabled", True):
        await run_blocking(maybe_refresh_news, cfg)


async def connectivity_loop(stop_event: asyncio.Event) -> None:
    log.info("Connectivity loop started (every %ss)", HEALTH_CHECK_SEC)
    await asyncio.sleep(2)
    while not stop_event.is_set():
        try:
            await run_connectivity_checks()
        except Exception:
            log.exception("Connectivity check failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEALTH_CHECK_SEC)
        except asyncio.TimeoutError:
            pass
