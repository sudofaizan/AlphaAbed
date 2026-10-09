from signals.classify import TradeSignal
from signals.trade_plan import build_trade_plan
from app.lot_sizing import compute_trade_volumes, sl_points_for_volume


def test_risk_usd_volume_from_sl_points():
    signal = TradeSignal(side="buy", symbol="XAUUSD", sl=1250, market=True)
    plan = build_trade_plan(
        signal,
        bid=2700.0,
        ask=2700.5,
        reward_risk_ratio=2.0,
        prefer_signal_tp=False,
        default_sl_points=None,
        point=0.01,
        sl_message_unit="points",
    )
    assert plan is not None
    cfg = {
        "lot_mode": "risk_usd",
        "risk_usd": 30.0,
        "volume": 0.1,
        "sl_message_unit": "points",
        "default_sl_points": 500,
    }
    mt5, cap, meta = compute_trade_volumes(cfg, signal=signal, plan=plan, point=0.01)
    assert meta["sl_points"] == 1250.0
    assert abs(mt5 - 0.024) < 0.001
    assert mt5 == cap


def test_sl_points_from_price_distance():
    signal = TradeSignal(side="buy", symbol="XAUUSD", sl=2650.0, market=True)
    plan = build_trade_plan(
        signal,
        bid=2700.0,
        ask=2700.5,
        reward_risk_ratio=2.0,
        prefer_signal_tp=False,
        default_sl_points=None,
        point=0.01,
        sl_message_unit="price",
    )
    pts = sl_points_for_volume(
        signal=signal,
        plan=plan,
        point=0.01,
        default_sl_points=None,
        sl_message_unit="price",
    )
    assert abs(pts - 5050.0) < 0.1
