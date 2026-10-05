"""Telegram fetch + classify."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timezone
from typing import Any

from app.config_store import load_config

from telethon import events
from telethon.errors import ChannelInvalidError, ChannelPrivateError, UsernameInvalidError

from signals.classify import classify_text, format_signal_line
from signals.trade_plan import build_trade_plan
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from telegram_util import build_client, require_env


SIGNAL_KINDS = {
    "open_signal",
    "close_all",
    "partial_close",
    "incomplete_signal",
    "sl_fragment",
}


def _msg_record(message, body: str) -> dict[str, Any]:
    when = message.date.replace(tzinfo=timezone.utc).isoformat()
    parsed = classify_text(body)
    return {
        "message_id": message.id,
        "date": when,
        "kind": parsed.kind,
        "summary": format_signal_line(parsed, message.id),
        "raw_text": body,
        "signal": _signal_dict(parsed.signal),
        "reason": parsed.reason,
    }


def _signal_dict(sig) -> dict | None:
    if not sig:
        return None
    return {
        "side": sig.side,
        "symbol": sig.symbol,
        "entry": sig.entry,
        "entry_min": sig.entry_min,
        "entry_max": sig.entry_max,
        "sl": sig.sl,
        "tp": sig.tp,
        "market": sig.market,
    }


async def test_telegram() -> dict[str, Any]:
    channel = require_env("CHANNEL")
    client, _, _ = build_client()
    async with client:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Telegram session not authorized"}
        try:
            entity = await client.get_entity(channel)
        except (UsernameInvalidError, ChannelInvalidError, ValueError) as e:
            return {"ok": False, "error": f"Channel: {e}"}
        except ChannelPrivateError:
            return {"ok": False, "error": "Not a member of the channel"}
        title = getattr(entity, "title", channel)
        latest = await client.get_messages(entity, limit=1)
        preview = ""
        mid = None
        if latest:
            preview = (latest[0].message or "")[:120]
            mid = latest[0].id
        return {
            "ok": True,
            "channel": channel,
            "title": title,
            "latest_message_id": mid,
            "preview": preview,
        }


async def fetch_and_classify(limit: int, cfg: dict) -> dict[str, Any]:
    channel = require_env("CHANNEL")
    kinds = set(cfg.get("signal_kinds_history") or list(SIGNAL_KINDS))
    client, _, _ = build_client()
    all_rows: list[dict] = []
    signals: list[dict] = []

    mt5 = AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )
    price_resp = mt5.get_price()
    bid = float(price_resp.get("bid", 0) or 0)
    ask = float(price_resp.get("ask", 0) or 0)
    point = float(price_resp.get("point", 0.01) or 0.01)

    async with client:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Telegram not authorized", "signals": []}
        try:
            entity = await client.get_entity(channel)
        except (UsernameInvalidError, ChannelInvalidError, ValueError) as e:
            return {"ok": False, "error": str(e), "signals": []}
        except ChannelPrivateError:
            return {"ok": False, "error": "Not a channel member", "signals": []}

        async for message in client.iter_messages(entity, limit=limit):
            body = (message.message or "").strip()
            if not body and message.media:
                body = f"[media: {type(message.media).__name__}]"
            row = _msg_record(message, body)
            all_rows.append(row)
            if row["kind"] in kinds:
                if row["kind"] in ("open_signal", "incomplete_signal") and row["signal"] and bid and ask:
                    from signals.classify import TradeSignal

                    s = row["signal"]
                    sig = TradeSignal(
                        side=s["side"],
                        symbol=s["symbol"],
                        entry=s.get("entry"),
                        entry_min=s.get("entry_min"),
                        entry_max=s.get("entry_max"),
                        sl=s.get("sl"),
                        tp=s.get("tp"),
                        market=bool(s.get("market")),
                    )
                    default_sl = (
                        float(cfg["default_sl_points"])
                        if cfg.get("allow_trade_without_sl")
                        else None
                    )
                    plan = build_trade_plan(
                        sig,
                        bid=bid,
                        ask=ask,
                        reward_risk_ratio=float(cfg["reward_risk_ratio"]),
                        prefer_signal_tp=bool(cfg["prefer_signal_tp"]),
                        default_sl_points=default_sl,
                        point=point,
                    )
                    if plan:
                        row["trade_plan"] = plan.__dict__
                    elif row["kind"] == "incomplete_signal" and not s.get("sl"):
                        row["trade_plan_note"] = "No SL — enable default SL points to preview/ trade"
                signals.append(row)

    return {
        "ok": True,
        "fetched": len(all_rows),
        "signal_count": len(signals),
        "signals": signals,
        "price": {"bid": bid, "ask": ask, "ok": price_resp.get("ok", False)},
    }


async def run_realtime_listener(stop_event: asyncio.Event, on_signal) -> None:
    """Push-based new messages (typically within ~1s of channel post)."""
    channel = require_env("CHANNEL")
    client, _, _ = build_client()
    await client.start()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram not authorized")
    entity = await client.get_entity(channel)
    tglog = logging.getLogger("alphaabed.telegram")

    @client.on(events.NewMessage(chats=entity))
    async def _handler(event):
        body = (event.message.message or "").strip()
        if not body:
            return
        row = _msg_record(event.message, body)
        cfg = load_config()
        await on_signal(row, cfg)

    tglog.info("Telegram realtime connected to %s", channel)
    while not stop_event.is_set():
        await asyncio.sleep(0.25)
    await client.disconnect()


async def poll_new_messages(
    cfg: dict,
    last_id: int,
    on_signal,
) -> int:
    """Fetch messages newer than last_id; returns max message id seen."""
    channel = require_env("CHANNEL")
    client, _, _ = build_client()
    max_id = last_id
    async with client:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram not authorized")
        entity = await client.get_entity(channel)
        batch = []
        async for message in client.iter_messages(entity, min_id=last_id, limit=50):
            if message.id <= last_id:
                continue
            max_id = max(max_id, message.id)
            body = (message.message or "").strip()
            if not body:
                continue
            batch.append(_msg_record(message, body))
        for row in reversed(batch):
            await on_signal(row, cfg)
    return max_id
