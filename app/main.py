"""AlphaAbed dashboard + automation (port 80)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.async_io import run_blocking
from app.config_store import load_config, save_config
from app.datetime_util import enrich_date_ist
from app.state import state
from app.telegram_service import test_telegram, fetch_and_classify
from app.test_trade import test_close_all, test_market_open
from app.worker import refresh_history_once, worker_loop
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.trade_plan import build_trade_plan

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alphaabed")

STATIC = Path(__file__).parent / "static"
_stop: asyncio.Event | None = None
_worker_task: asyncio.Task | None = None


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


class PreviewBody(BaseModel):
    text: str


async def _bootstrap() -> None:
    try:
        await refresh_history_once()
    except Exception:
        log.exception("Initial history refresh failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _stop, _worker_task
    _stop = asyncio.Event()
    asyncio.create_task(_bootstrap())
    _worker_task = asyncio.create_task(worker_loop(_stop))
    yield
    if _stop:
        _stop.set()
    if _worker_task:
        await _worker_task


app = FastAPI(title="AlphaAbed", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health():
    return {"ok": True, "service": "alphaabed"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def api_status():
    with state.lock:
        return {
            "worker_running": state.worker_running,
            "last_poll_at": state.last_poll_at,
            "last_telegram_ok": state.last_telegram_ok,
            "last_telegram_error": state.last_telegram_error,
            "last_mt5_ok": state.last_mt5_ok,
            "today_pnl": state.today_pnl,
            "account_equity": state.account_equity,
            "last_message_id": state.last_message_id,
            "config": load_config(),
        }


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
    with state.lock:
        state.last_telegram_ok = result.get("ok", False)
        state.last_telegram_error = result.get("error")
    return result


@app.post("/api/test/trade/buy")
async def api_test_trade_buy():
    cfg = load_config()
    return await run_blocking(test_market_open, cfg, "buy")


@app.post("/api/test/trade/sell")
async def api_test_trade_sell():
    cfg = load_config()
    return await run_blocking(test_market_open, cfg, "sell")


@app.post("/api/test/trade/close-all")
async def api_test_trade_close_all():
    cfg = load_config()
    return await run_blocking(test_close_all, cfg)


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
    with state.lock:
        state.last_mt5_ok = ok
        if account.get("ok"):
            today = account.get("today") or {}
            state.today_pnl = today.get("closed_pl")
            state.account_equity = account.get("equity")
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
