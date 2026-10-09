from signals.classify import TradeSignal
from signals.trade_plan import build_trade_plan
from app.lot_sizing import compute_trade_volumes, sl_points_from_plan


def test_risk_usd_volume_from_sl_price():
    signal = TradeSignal(side="buy", symbol="XAUUSD", sl=2650.0, market=True)
    plan = build_trade_plan(
        signal,
        bid=2700.0,
        ask=2700.5,
        reward_risk_ratio=2.0,
        prefer_signal_tp=False,
        default_sl_points=None,
        point=0.01,
    )
    assert plan is not None
    pts = sl_points_from_plan(plan, 0.01)
    assert abs(pts - 5050.0) < 0.1

    cfg = {
        "lot_mode": "risk_usd",
        "risk_usd": 30.0,
        "volume": 0.1,
        "default_sl_points": 500,
    }
    mt5, cap, meta = compute_trade_volumes(cfg, signal=signal, plan=plan, point=0.01)
    assert meta["sl_points"] == round(pts, 2)
    expected = max(0.01, round(30.0 / pts, 3))
    assert mt5 == expected
    assert mt5 == cap
