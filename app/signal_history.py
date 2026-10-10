"""Merge Telegram + WhatsApp rows for dashboard signal history."""

from __future__ import annotations

from typing import Any

from signals.classify import TradeSignal
from signals.trade_plan import build_trade_plan


def history_key(row: dict[str, Any]) -> str:
    src = (row.get("source") or "telegram").lower()
    mid = str(row.get("message_id") or "")
    return f"{src}:{mid}"


def should_show_in_history(row: dict[str, Any], cfg: dict) -> bool:
    kind = row.get("kind")
    if (row.get("source") or "").lower() == "whatsapp" and kind == "open_signal":
        return True
    kinds = cfg.get("signal_kinds_history") or []
    return kind in kinds


def enrich_row_trade_plan(row: dict[str, Any], cfg: dict, *, price: dict | None = None) -> None:
    """Attach trade_plan preview for open signals (display only)."""
    if row.get("kind") != "open_signal" or not row.get("signal"):
        return
    if row.get("trade_plan"):
        return
    from app.mt5_accounts import primary_mt5_client

    client = primary_mt5_client(cfg)
    price_resp = price if price else client.get_price()
    if not price_resp.get("ok"):
        return
    bid = float(price_resp["bid"])
    ask = float(price_resp["ask"])
    point = float(price_resp.get("point") or 0.01)
    s = row["signal"]
    prefer_tp = bool(cfg.get("prefer_signal_tp")) or (row.get("source") == "whatsapp")
    sig = TradeSignal(
        side=s["side"],
        symbol=s.get("symbol") or "XAUUSD",
        entry=s.get("entry"),
        sl=s.get("sl"),
        tp=s.get("tp"),
        tp_levels=s.get("tp_levels"),
        market=True,
    )
    default_sl = float(cfg["default_sl_points"]) if cfg.get("allow_trade_without_sl") else None
    plan = build_trade_plan(
        sig,
        bid=bid,
        ask=ask,
        reward_risk_ratio=float(cfg["reward_risk_ratio"]),
        prefer_signal_tp=prefer_tp,
        default_sl_points=default_sl,
        point=point,
    )
    if plan:
        row["trade_plan"] = plan.__dict__


def merge_signal_histories(*lists: list[dict[str, Any]], limit: int = 200) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for items in lists:
        for row in items:
            if not row:
                continue
            key = history_key(row)
            prev = by_key.get(key)
            if prev:
                merged = {**prev, **row}
                if prev.get("execution") and not row.get("execution"):
                    merged["execution"] = prev["execution"]
                by_key[key] = merged
            else:
                by_key[key] = dict(row)

    def sort_key(r: dict[str, Any]) -> str:
        return str(r.get("date") or "")

    out = sorted(by_key.values(), key=sort_key, reverse=True)
    return out[:limit]


def upsert_history(history: list[dict[str, Any]], row: dict[str, Any], *, limit: int = 200) -> list[dict[str, Any]]:
    key = history_key(row)
    kept = [h for h in history if history_key(h) != key]
    return merge_signal_histories([row], kept, limit=limit)
