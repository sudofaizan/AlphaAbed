"""Execute trades via AlphaFX API from classified rows."""

from __future__ import annotations

import logging
from typing import Any

from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.classify import TradeSignal, classify_text, merge_sl_fragment
from signals.trade_plan import build_trade_plan

log = logging.getLogger("alphaabed.trading")

_pending: TradeSignal | None = None


async def process_signal_row(row: dict[str, Any], cfg: dict) -> dict[str, Any] | None:
    global _pending
    parsed = classify_text(row.get("raw_text", ""))
    kind = parsed.kind

    if kind == "sl_fragment" and parsed.signal and _pending:
        merged = merge_sl_fragment(_pending, row.get("raw_text", ""))
        if merged:
            _pending = None
            parsed.kind = "open_signal"
            parsed.signal = merged
            kind = "open_signal"

    if kind == "incomplete_signal" and parsed.signal and parsed.signal.sl is None:
        if cfg.get("allow_trade_without_sl"):
            kind = "open_signal"
        else:
            _pending = parsed.signal
            return None

    if kind not in ("open_signal", "close_all", "partial_close"):
        return None

    if not cfg.get("auto_trade"):
        return {"action": "skipped", "reason": "auto_trade disabled", "kind": kind}

    client = AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )

    if kind == "close_all":
        return {"action": "close_all", "result": client.close_all(cfg["mt5_symbol"])}

    if kind == "partial_close":
        vol = float(cfg["volume"]) / 2
        return {
            "action": "partial_close",
            "result": client.close_partial(cfg["mt5_symbol"], vol),
        }

    if not parsed.signal:
        return None

    signal = parsed.signal
    if signal.sl is None and not cfg.get("allow_trade_without_sl"):
        return {"action": "skipped", "reason": "no SL in message"}
    if signal.sl is None and not cfg.get("default_sl_points"):
        return {"action": "skipped", "reason": "no SL and no default_sl_points"}

    price = client.get_price()
    if not price.get("ok"):
        return {"action": "error", "reason": "getPrice failed", "detail": price}

    bid = float(price["bid"])
    ask = float(price["ask"])
    point = float(price.get("point") or 0.01)
    default_sl = float(cfg["default_sl_points"]) if cfg.get("allow_trade_without_sl") else None

    plan = build_trade_plan(
        signal,
        bid=bid,
        ask=ask,
        reward_risk_ratio=float(cfg["reward_risk_ratio"]),
        prefer_signal_tp=bool(cfg["prefer_signal_tp"]),
        default_sl_points=default_sl,
        point=point,
    )
    if not plan or plan.sl is None:
        return {"action": "skipped", "reason": "could not build trade plan"}

    order_type = plan.side
    if signal.entry_min is not None and signal.entry_max is not None:
        mid = (signal.entry_min + signal.entry_max) / 2
        order_type = "buy_limit" if plan.side == "buy" else "sell_limit"
        result = client.place_order(
            order_type=order_type,
            volume=float(cfg["volume"]),
            sl=plan.sl,
            tp=plan.tp,
            price=mid,
            comment=f"tg:{row.get('message_id')}",
        )
    else:
        result = client.place_order(
            order_type=order_type,
            volume=float(cfg["volume"]),
            sl=plan.sl,
            tp=plan.tp,
            comment=f"tg:{row.get('message_id')}",
        )

    return {
        "action": "open",
        "plan": plan.__dict__,
        "result": result,
        "message_id": row.get("message_id"),
    }
