"""AlphaAbed dashboard + automation (port 80)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config_store import load_config, save_config
from app.state import state
from app.telegram_service import test_telegram, fetch_and_classify
from app.worker import refresh_history_once, worker_loop
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.trade_plan import build_trade_plan

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alphaabed")

STATIC = Path(__file__).parent / "static"
_stop: asyncio.Event | None = None
_worker_task: asyncio.Task | None = None


class ConfigUpdate(BaseModel):
    poll_interval_sec: int | None = None
    mt5_base_url: str | None = None
    mt5_api_key: str | None = None
    mt5_symbol: str | None = None
    volume: float | None = None
    reward_risk_ratio: float | None = None
    prefer_signal_tp: bool | None = None
    auto_trade: bool | None = None
    allow_trade_without_sl: bool | None = None
    default_sl_points: float | None = None
    telegram_fetch_limit: int | None = None


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
    return save_config(updates)


@app.post("/api/test/telegram")
async def api_test_telegram():
    result = await test_telegram()
    with state.lock:
        state.last_telegram_ok = result.get("ok", False)
        state.last_telegram_error = result.get("error")
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
    health = client.health()
    account = client.account_health()
    price = client.get_price()
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
    account = client.account_health()
    price = client.get_price()
    return {"account": account, "price": price}


@app.post("/api/signals/refresh")
async def api_signals_refresh():
    return await refresh_history_once()


@app.get("/api/signals/history")
async def api_signals_history():
    with state.lock:
        return {"signals": list(state.signal_history), "count": len(state.signal_history)}


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
        price = client.get_price()
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
