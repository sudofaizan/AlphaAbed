"""AlphaAbed dashboard + automation (port 80)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.async_io import run_blocking
from app.config_store import load_config, save_config
from app.datetime_util import enrich_date_ist
from app.state import state
from app.telegram_service import test_telegram, fetch_and_classify
from app.dual_trade import test_capiffy_connection
from app.test_trade import test_close_all, test_market_open
from app.connectivity import (
    connectivity_loop,
    record_capiffy,
    record_mt5,
    record_telegram,
    run_connectivity_checks,
)
from app.datetime_util import format_card_time_ist
from app.news_blackout import blackout_status
from app.news_service import get_news_snapshot, refresh_news_sync
from app.ui_auth import create_session, revoke_session, verify_password, verify_session
from app.worker import refresh_history_once, worker_loop
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.trade_plan import build_trade_plan

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alphaabed")

STATIC = Path(__file__).parent / "static"
_stop: asyncio.Event | None = None
_worker_task: asyncio.Task | None = None
_connectivity_task: asyncio.Task | None = None


class ConfigUpdate(BaseModel):
    poll_interval_sec: Optional[int] = None
    mt5_base_url: Optional[str] = None
    mt5_api_key: Optional[str] = None
    mt5_symbol: Optional[str] = None
    mt5_trade_comment: Optional[str] = None
    volume: Optional[float] = None
    reward_risk_ratio: Optional[float] = None
    prefer_signal_tp: Optional[bool] = None
    auto_trade: Optional[bool] = None
    allow_trade_without_sl: Optional[bool] = None
    default_sl_points: Optional[float] = None
    telegram_fetch_limit: Optional[int] = None
    telegram_realtime: Optional[bool] = None
    account_refresh_sec: Optional[int] = None
    trade_mt5: Optional[bool] = None
    capiffy_enabled: Optional[bool] = None
    trade_capiffy: Optional[bool] = None
    capiffy_volume: Optional[float] = None
    capiffy_symbol: Optional[str] = None
    capiffy_account_id: Optional[str] = None
    news_calendar_enabled: Optional[bool] = None
    news_hours_ahead: Optional[int] = None
    news_impact: Optional[str] = None
    news_currency: Optional[str] = None
    news_refresh_sec: Optional[int] = None
    capiffy_news_blackout: Optional[bool] = None
    capiffy_news_minutes_before: Optional[int] = None
    capiffy_news_minutes_after: Optional[int] = None


class PreviewBody(BaseModel):
    text: str


class LoginBody(BaseModel):
    password: str


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/login",):
            token = request.headers.get("X-XAUBeast-Token")
            if not verify_session(token):
                return JSONResponse(
                    {"ok": False, "error": "unauthorized — unlock dashboard"},
                    status_code=401,
                )
        return await call_next(request)


async def _bootstrap() -> None:
    try:
        await run_connectivity_checks()
    except Exception:
        log.exception("Initial connectivity check failed")
    try:
        await refresh_history_once()
    except Exception:
        log.exception("Initial history refresh failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _stop, _worker_task, _connectivity_task
    _stop = asyncio.Event()
    asyncio.create_task(_bootstrap())
    _worker_task = asyncio.create_task(worker_loop(_stop))
    _connectivity_task = asyncio.create_task(connectivity_loop(_stop))
    yield
    if _stop:
        _stop.set()
    if _connectivity_task:
        await _connectivity_task
    if _worker_task:
        await _worker_task


app = FastAPI(title="XAUBeast - ALPHAFX", lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health():
    return {"ok": True, "service": "xaubeast-alphafx"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/settings")
async def settings_page():
    return FileResponse(STATIC / "settings.html")


@app.post("/api/login")
async def api_login(body: LoginBody):
    if not verify_password(body.password):
        return JSONResponse({"ok": False, "error": "Invalid password"}, status_code=401)
    token = create_session()
    return {"ok": True, "token": token}


@app.get("/api/session")
async def api_session(request: Request):
    token = request.headers.get("X-XAUBeast-Token")
    if verify_session(token):
        return {"ok": True}
    return JSONResponse({"ok": False}, status_code=401)


@app.post("/api/logout")
async def api_logout(request: Request):
    revoke_session(request.headers.get("X-XAUBeast-Token"))
    return {"ok": True}


@app.get("/api/status")
async def api_status():
    cfg = load_config()
    news_blk = blackout_status(cfg)
    with state.lock:
        tg_at = state.last_telegram_ok_at
        mt5_at = state.last_mt5_ok_at
        cap_at = state.last_capiffy_ok_at
        poll_at = state.last_poll_at
        return {
            "worker_running": state.worker_running,
            "last_poll_at": poll_at,
            "last_poll_at_ist": format_card_time_ist(poll_at),
            "last_telegram_ok": state.last_telegram_ok,
            "last_telegram_error": state.last_telegram_error,
            "last_telegram_ok_at": tg_at,
            "last_telegram_ok_at_ist": format_card_time_ist(tg_at),
            "last_mt5_ok": state.last_mt5_ok,
            "last_mt5_error": state.last_mt5_error,
            "last_mt5_ok_at": mt5_at,
            "last_mt5_ok_at_ist": format_card_time_ist(mt5_at),
            "last_capiffy_ok": state.last_capiffy_ok,
            "last_capiffy_error": state.last_capiffy_error,
            "last_capiffy_ok_at": cap_at,
            "last_capiffy_ok_at_ist": format_card_time_ist(cap_at),
            "health_check_interval_sec": 60,
            "today_pnl": state.today_pnl,
            "account_equity": state.account_equity,
            "last_message_id": state.last_message_id,
            "config": cfg,
            **news_blk,
        }


@app.get("/api/news")
async def api_news():
    cfg = load_config()
    snap = await run_blocking(get_news_snapshot, cfg)
    blk = blackout_status(cfg)
    return {**snap, **blk}


@app.post("/api/news/refresh")
async def api_news_refresh():
    cfg = load_config()
    snap = await run_blocking(refresh_news_sync, cfg)
    blk = blackout_status(cfg)
    return {**snap, **blk}


@app.get("/api/config")
async def get_config():
    return load_config()


@app.put("/api/config")
async def put_config(body: ConfigUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg = save_config(updates)
    return {
        "ok": True,
        "message": "Settings saved successfully.",
        "config": cfg,
        "saved_at": cfg.get("config_saved_at"),
    }


@app.post("/api/test/telegram")
async def api_test_telegram():
    result = await test_telegram()
    record_telegram(bool(result.get("ok")), result.get("error"))
    return result


@app.post("/api/test/trade/buy")
async def api_test_trade_buy(platform: str = Query("mt5")):
    cfg = load_config()
    return await run_blocking(test_market_open, cfg, "buy", platform)


@app.post("/api/test/trade/sell")
async def api_test_trade_sell(platform: str = Query("mt5")):
    cfg = load_config()
    return await run_blocking(test_market_open, cfg, "sell", platform)


@app.post("/api/test/trade/close-all")
async def api_test_trade_close_all(platform: str = Query("mt5")):
    cfg = load_config()
    return await run_blocking(test_close_all, cfg, platform)


@app.post("/api/test/capiffy")
async def api_test_capiffy():
    cfg = load_config()
    result = await run_blocking(test_capiffy_connection, cfg)
    record_capiffy(bool(result.get("ok")), result.get("error"))
    return result


@app.post("/api/test/mt5")
async def api_test_mt5():
    cfg = load_config()
    client = AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )
    health = await run_blocking(client.health)
    account = await run_blocking(client.account_health)
    price = await run_blocking(client.get_price)
    ok = bool(health.get("ok")) and bool(account.get("ok"))
    err = None if ok else (health.get("error") or account.get("error"))
    record_mt5(ok, err, account if account.get("ok") else None)
    return {"ok": ok, "health": health, "account": account, "price": price}


@app.get("/api/account")
async def api_account():
    cfg = load_config()
    client = AlphaFxClient(
        AlphaFxConfig(cfg["mt5_base_url"], cfg["mt5_api_key"], cfg["mt5_symbol"])
    )
    account = await run_blocking(client.account_health)
    price = await run_blocking(client.get_price)
    return {"account": account, "price": price}


@app.post("/api/signals/refresh")
async def api_signals_refresh():
    result = await refresh_history_once()
    if result.get("signals"):
        result["signals"] = [enrich_date_ist(s) for s in result["signals"]]
    return result


@app.get("/api/signals/history")
async def api_signals_history():
    with state.lock:
        signals = [enrich_date_ist(s) for s in state.signal_history]
        return {"signals": signals, "count": len(signals)}


@app.get("/api/events")
async def api_events():
    with state.lock:
        return {"events": list(state.recent_events)}


@app.post("/api/preview")
async def api_preview(body: PreviewBody):
    cfg = load_config()
    from signals.classify import classify_text, format_signal_line

    parsed = classify_text(body.text)
    out: dict[str, Any] = {
        "kind": parsed.kind,
        "summary": format_signal_line(parsed),
        "reason": parsed.reason,
    }
    if parsed.signal:
        client = AlphaFxClient(
            AlphaFxConfig(cfg["mt5_base_url"], cfg["mt5_api_key"], cfg["mt5_symbol"])
        )
        price = await run_blocking(client.get_price)
        if price.get("ok") and parsed.kind in ("open_signal", "incomplete_signal"):
            sig = parsed.signal
            plan = build_trade_plan(
                sig,
                bid=float(price["bid"]),
                ask=float(price["ask"]),
                reward_risk_ratio=float(cfg["reward_risk_ratio"]),
                prefer_signal_tp=bool(cfg["prefer_signal_tp"]),
                default_sl_points=float(cfg["default_sl_points"])
                if cfg.get("allow_trade_without_sl")
                else None,
                point=float(price.get("point") or 0.01),
            )
            if plan:
                out["trade_plan"] = plan.__dict__
        out["price"] = price
    return out
