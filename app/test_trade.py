"""Small live orders to verify MT5 / Capiffy (parallel when both selected)."""

from __future__ import annotations

from typing import Any

from app.dual_trade import close_all_parallel, open_market_parallel, should_trade_capiffy, should_trade_mt5
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.classify import TradeSignal
from signals.trade_plan import build_trade_plan

TEST_VOLUME_MT5 = 0.01


def _client_from_cfg(cfg: dict) -> AlphaFxClient:
    return AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )


def _cfg_for_platform(cfg: dict, platform: str) -> dict:
    p = platform.lower().strip()
    if p not in ("mt5", "capiffy", "both"):
        raise ValueError("platform must be mt5, capiffy, or both")
    out = dict(cfg)
    out["trade_mt5"] = p in ("mt5", "both")
    out["capiffy_enabled"] = p in ("capiffy", "both")
    out["trade_capiffy"] = p in ("capiffy", "both")
    return out


def test_market_open(cfg: dict, side: str, platform: str = "mt5") -> dict[str, Any]:
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}

    try:
        eff = _cfg_for_platform(cfg, platform)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if not should_trade_mt5(eff) and not should_trade_capiffy(eff):
        return {"ok": False, "error": "no platform selected"}

    client = _client_from_cfg(cfg)
    price = client.get_price()
    if not price.get("ok"):
        return {"ok": False, "error": "getPrice failed", "detail": price}

    bid = float(price["bid"])
    ask = float(price["ask"])
    point = float(price.get("point") or 0.01)
    signal = TradeSignal(side=side, symbol=cfg["mt5_symbol"], market=True)
    plan = build_trade_plan(
        signal,
        bid=bid,
        ask=ask,
        reward_risk_ratio=float(cfg.get("reward_risk_ratio") or 2.0),
        prefer_signal_tp=bool(cfg.get("prefer_signal_tp")),
        default_sl_points=float(cfg.get("default_sl_points") or 500),
        point=point,
    )
    if not plan or plan.sl is None:
        return {"ok": False, "error": "could not build trade plan"}

    cap_vol = float(eff.get("capiffy_volume") or TEST_VOLUME_MT5)
    result = open_market_parallel(
        eff,
        plan,
        mt5_volume=TEST_VOLUME_MT5 if eff.get("trade_mt5") else None,
        capiffy_volume=cap_vol if eff.get("trade_capiffy") else None,
    )
    return {
        "ok": bool(result.get("ok")),
        "action": "test_open",
        "platform": platform,
        "side": side,
        "mt5_volume": TEST_VOLUME_MT5 if eff.get("trade_mt5") else None,
        "capiffy_volume": cap_vol if eff.get("trade_capiffy") else None,
        "plan": plan.__dict__,
        "result": result,
    }


def test_close_all(cfg: dict, platform: str = "mt5") -> dict[str, Any]:
    try:
        eff = _cfg_for_platform(cfg, platform)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if platform.lower() == "capiffy":
        return {
            "ok": False,
            "action": "test_close_all",
            "platform": platform,
            "error": "Capiffy close is not supported — close positions on capiffy.com (MT5 only here).",
        }

    eff["trade_capiffy"] = False
    eff["capiffy_enabled"] = False
    result = close_all_parallel(eff)
    return {
        "ok": bool(result.get("ok")),
        "action": "test_close_all",
        "platform": platform,
        "result": result,
    }
