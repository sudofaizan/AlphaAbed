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


def lot_profile_for_source(cfg: dict, source: str) -> dict[str, Any]:
    """
    Lot settings for Telegram (ABD / TE) vs WhatsApp (WASIG).
    Per-source keys win; legacy volume / lot_mode / risk_usd / capiffy_volume are fallback.
    """
    src = (source or "telegram").lower()
    prefix = "whatsapp_" if src == "whatsapp" else "telegram_"

    def _pick(name: str, legacy_key: str, default: Any) -> Any:
        val = cfg.get(f"{prefix}{name}")
        if val is None:
            val = cfg.get(legacy_key, default)
        return val

    return {
        "source": src,
        "lot_mode": str(_pick("lot_mode", "lot_mode", "fixed")).lower(),
        "volume": float(_pick("volume", "volume", 0.1)),
        "risk_usd": float(_pick("risk_usd", "risk_usd", 30.0)),
        "capiffy_volume": float(_pick("capiffy_volume", "capiffy_volume", 0.01)),
    }


def compute_trade_volumes(
    cfg: dict,
    *,
    source: str = "telegram",
    signal: TradeSignal,
    plan: TradePlan,
    point: float,
) -> tuple[float, float, dict[str, Any]]:
    """
    Returns (mt5_volume, capiffy_volume, meta).
    risk_usd: lot ≈ risk_usd / sl_points, where sl_points = |entry − SL price| / point.
    """
    profile = lot_profile_for_source(cfg, source)
    mode = profile["lot_mode"]
    fixed_mt5 = profile["volume"]
    fixed_cap = profile["capiffy_volume"]

    if mode != "risk_usd":
        return fixed_mt5, fixed_cap, {
            "lot_mode": "fixed",
            "signal_source": profile["source"],
            "mt5_volume": fixed_mt5,
            "capiffy_volume": fixed_cap,
        }

    risk = profile["risk_usd"]
    if risk <= 0:
        raise ValueError("risk_usd must be > 0")

    if signal.sl is None and not cfg.get("default_sl_points"):
        raise ValueError("risk_usd lot mode requires SL price in the signal")

    sl_pts = sl_points_from_plan(plan, point)
    if not sl_pts:
        default_pts = float(cfg["default_sl_points"]) if cfg.get("default_sl_points") else None
        if default_pts and default_pts > 0:
            sl_pts = default_pts
    if not sl_pts or sl_pts <= 0:
        raise ValueError("could not determine SL distance in points for $-risk sizing")

    usd_per_point_per_lot = float(cfg.get("mt5_usd_per_point_per_lot") or 1.0)
    if usd_per_point_per_lot <= 0:
        raise ValueError("mt5_usd_per_point_per_lot must be > 0")

    vol = round_volume(risk / (sl_pts * usd_per_point_per_lot))
    est_loss = round(sl_pts * vol * usd_per_point_per_lot, 2)
    meta = {
        "lot_mode": "risk_usd",
        "signal_source": profile["source"],
        "risk_usd": risk,
        "entry": plan.entry,
        "sl_price": plan.sl,
        "sl_points": round(sl_pts, 2),
        "mt5_usd_per_point_per_lot": usd_per_point_per_lot,
        "estimated_sl_loss_usd": est_loss,
        "volume": vol,
        "mt5_volume": vol,
        "capiffy_volume": vol,
    }
    return vol, vol, meta
