"""Build SL/TP and R:R from signal + live quote."""

from __future__ import annotations

from dataclasses import dataclass

from signals.classify import TradeSignal


@dataclass
class TradePlan:
    side: str
    symbol: str
    entry: float
    sl: float | None
    tp: float | None
    risk_points: float | None
    reward_points: float | None
    reward_risk_ratio: float | None
    bid: float
    ask: float
    used_signal_tp: bool
    notes: str = ""


def _entry_price(side: str, bid: float, ask: float) -> float:
    return ask if side == "buy" else bid


def build_trade_plan(
    signal: TradeSignal,
    *,
    bid: float,
    ask: float,
    reward_risk_ratio: float,
    prefer_signal_tp: bool,
    default_sl_points: float | None,
    point: float = 0.01,
) -> TradePlan | None:
    side = signal.side
    entry = _entry_price(side, bid, ask)

    sl = signal.sl
    if sl is None and default_sl_points is not None and default_sl_points > 0:
        dist = default_sl_points * point
        sl = entry - dist if side == "buy" else entry + dist

    if sl is None:
        return None

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    used_signal_tp = False
    tp = signal.tp
    if tp is not None and prefer_signal_tp:
        used_signal_tp = True
    else:
        reward = risk * reward_risk_ratio
        tp = entry + reward if side == "buy" else entry - reward

    reward_pts = abs(tp - entry) if tp is not None else None
    rr = (reward_pts / risk) if reward_pts is not None and risk else None

    return TradePlan(
        side=side,
        symbol=signal.symbol,
        entry=round(entry, 2),
        sl=round(sl, 2),
        tp=round(tp, 2) if tp is not None else None,
        risk_points=round(risk, 2),
        reward_points=round(reward_pts, 2) if reward_pts is not None else None,
        reward_risk_ratio=round(rr, 2) if rr is not None else None,
        bid=bid,
        ask=ask,
        used_signal_tp=used_signal_tp,
    )
