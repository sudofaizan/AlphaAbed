"""Fixed lot vs $-risk lot sizing (SL distance in points from live price vs message SL price)."""

from __future__ import annotations

from typing import Any

from signals.classify import TradeSignal
from signals.trade_plan import TradePlan


def sl_points_from_plan(plan: TradePlan, point: float) -> float | None:
    """Points between market entry and stop price (MT5 symbol point size)."""
    if plan.sl is None or point <= 0:
        return None
    pts = abs(plan.entry - plan.sl) / point
    return pts if pts > 0 else None


def round_volume(vol: float, *, min_vol: float = 0.01, step: float = 0.001) -> float:
    if vol < min_vol:
        return min_vol
    rounded = round(vol / step) * step
    return max(min_vol, round(rounded, 3))


def compute_trade_volumes(
    cfg: dict,
    *,
    signal: TradeSignal,
    plan: TradePlan,
    point: float,
) -> tuple[float, float, dict[str, Any]]:
    """
    Returns (mt5_volume, capiffy_volume, meta).
    risk_usd: lot ≈ risk_usd / sl_points, where sl_points = |entry − SL price| / point.
    """
    mode = (cfg.get("lot_mode") or "fixed").lower()
    fixed_mt5 = float(cfg.get("volume") or 0.1)
    fixed_cap = float(cfg.get("capiffy_volume") or fixed_mt5)

    if mode != "risk_usd":
        return fixed_mt5, fixed_cap, {"lot_mode": "fixed", "mt5_volume": fixed_mt5, "capiffy_volume": fixed_cap}

    risk = float(cfg.get("risk_usd") or 30.0)
    if risk <= 0:
        raise ValueError("risk_usd must be > 0")

    if signal.sl is None and not cfg.get("default_sl_points"):
        raise ValueError("risk_usd lot mode requires SL price in the Telegram message")

    sl_pts = sl_points_from_plan(plan, point)
    if not sl_pts:
        default_pts = float(cfg["default_sl_points"]) if cfg.get("default_sl_points") else None
        if default_pts and default_pts > 0:
            sl_pts = default_pts
    if not sl_pts or sl_pts <= 0:
        raise ValueError("could not determine SL distance in points for $-risk sizing")

    vol = round_volume(risk / sl_pts)
    meta = {
        "lot_mode": "risk_usd",
        "risk_usd": risk,
        "entry": plan.entry,
        "sl_price": plan.sl,
        "sl_points": round(sl_pts, 2),
        "volume": vol,
        "mt5_volume": vol,
        "capiffy_volume": vol,
    }
    return vol, vol, meta
