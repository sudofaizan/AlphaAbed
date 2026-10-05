"""Background Telegram / MT5 / Capiffy connectivity checks (every ~60s)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.async_io import run_blocking
from app.config_store import load_config
from app.dual_trade import test_capiffy_connection
from app.news_service import maybe_refresh_news
from app.state import state
from app.telegram_service import test_telegram
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig

log = logging.getLogger("alphaabed.connectivity")

HEALTH_CHECK_SEC = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_telegram(ok: bool, error: str | None = None) -> None:
    with state.lock:
        state.last_telegram_ok = ok
        if ok:
            state.last_telegram_ok_at = _utc_now_iso()
            state.last_telegram_error = None
        elif error is not None:
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
    client = AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )
    health = await run_blocking(client.health)
    account = await run_blocking(client.account_health)
    ok = bool(health.get("ok")) and bool(account.get("ok"))
    err = None
    if not ok:
        err = health.get("error") or account.get("error") or "MT5 check failed"
    record_mt5(ok, err, account if account.get("ok") else None)
    return {"ok": ok, "error": err}


async def run_connectivity_checks(cfg: dict | None = None) -> None:
    cfg = cfg or load_config()

    tg = await test_telegram()
    record_telegram(bool(tg.get("ok")), tg.get("error"))

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
