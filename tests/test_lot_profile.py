from app.lot_sizing import lot_profile_for_source, compute_trade_volumes
from signals.classify import TradeSignal
from signals.trade_plan import build_trade_plan


def test_separate_whatsapp_and_telegram_fixed_lots():
    cfg = {
        "telegram_lot_mode": "fixed",
        "telegram_volume": 0.2,
        "telegram_capiffy_volume": 0.03,
        "whatsapp_lot_mode": "fixed",
        "whatsapp_volume": 0.05,
        "whatsapp_capiffy_volume": 0.02,
    }
    signal = TradeSignal(side="buy", symbol="XAUUSD", sl=3900.0, market=True)
    plan = build_trade_plan(
        signal,
        bid=3995.0,
        ask=3996.0,
        reward_risk_ratio=2.0,
        prefer_signal_tp=False,
        default_sl_points=None,
        point=0.01,
    )
    assert plan is not None
    te_mt5, te_cap, te_meta = compute_trade_volumes(
        cfg, source="telegram", signal=signal, plan=plan, point=0.01
    )
    wa_mt5, wa_cap, wa_meta = compute_trade_volumes(
        cfg, source="whatsapp", signal=signal, plan=plan, point=0.01
    )
    assert te_mt5 == 0.2 and te_cap == 0.03
    assert wa_mt5 == 0.05 and wa_cap == 0.02
    assert te_meta["signal_source"] == "telegram"
    assert wa_meta["signal_source"] == "whatsapp"
