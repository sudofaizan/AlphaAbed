"""Fixed lot vs $-risk lot sizing (uses SL distance in points)."""

from __future__ import annotations

from typing import Any

from signals.classify import TradeSignal
from signals.sl_util import sl_message_is_points
from signals.trade_plan import TradePlan


def sl_points_for_volume(
    *,
    signal: TradeSignal,
    plan: TradePlan,
    point: float,
    default_sl_points: float | None,
    sl_message_unit: str,
) -> float | None:
    entry = plan.entry
    if signal.sl is not None and sl_message_is_points(signal.sl, entry, sl_message_unit):
        pts = float(signal.sl)
        return pts if pts > 0 else None
    if plan.sl is not None and point > 0:
        pts = abs(entry - plan.sl) / point
        return pts if pts > 0 else None
    if default_sl_points is not None and default_sl_points > 0:
        return float(default_sl_points)
    return None


def round_volume(vol: float, *, min_vol: float = 0.01, step: float = 0.001) -> float:
    if vol < min_vol:
        return min_vol
    # round to 3 decimals (0.001 lots)
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
    In risk_usd mode both platforms use the same calculated lot.
    """
    mode = (cfg.get("lot_mode") or "fixed").lower()
    fixed_mt5 = float(cfg.get("volume") or 0.1)
    fixed_cap = float(cfg.get("capiffy_volume") or fixed_mt5)

    if mode != "risk_usd":
        return fixed_mt5, fixed_cap, {"lot_mode": "fixed", "mt5_volume": fixed_mt5, "capiffy_volume": fixed_cap}

    risk = float(cfg.get("risk_usd") or 30.0)
    if risk <= 0:
        raise ValueError("risk_usd must be > 0")

    default_pts = float(cfg["default_sl_points"]) if cfg.get("default_sl_points") else None
    if signal.sl is None and not default_pts:
        raise ValueError("risk_usd lot mode requires SL in message or default_sl_points")

    sl_pts = sl_points_for_volume(
        signal=signal,
        plan=plan,
        point=point,
        default_sl_points=default_pts,
        sl_message_unit=str(cfg.get("sl_message_unit") or "auto"),
    )
    if not sl_pts or sl_pts <= 0:
        raise ValueError("could not determine SL points for $-risk sizing")

    vol = round_volume(risk / sl_pts)
    meta = {
        "lot_mode": "risk_usd",
        "risk_usd": risk,
        "sl_points": round(sl_pts, 2),
        "volume": vol,
        "mt5_volume": vol,
        "capiffy_volume": vol,
    }
    return vol, vol, meta
