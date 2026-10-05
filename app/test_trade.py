"""Small live orders to verify MT5 API (0.01 lot)."""

from __future__ import annotations

from typing import Any

from signals.alphafx_client import AlphaFxClient, AlphaFxConfig

TEST_VOLUME = 0.01


def _client_from_cfg(cfg: dict) -> AlphaFxClient:
    return AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )


def _sl_tp(side: str, entry: float, point: float, sl_points: float, rr: float) -> tuple[float, float]:
    dist = sl_points * point
    if side == "buy":
        sl = entry - dist
        tp = entry + dist * rr
    else:
        sl = entry + dist
        tp = entry - dist * rr
    return round(sl, 2), round(tp, 2)


def test_market_open(cfg: dict, side: str) -> dict[str, Any]:
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}

    client = _client_from_cfg(cfg)
    price = client.get_price()
    if not price.get("ok"):
        return {"ok": False, "error": "getPrice failed", "detail": price}

    bid = float(price["bid"])
    ask = float(price["ask"])
    point = float(price.get("point") or 0.01)
    entry = ask if side == "buy" else bid
    sl_pts = float(cfg.get("default_sl_points") or 500)
    rr = float(cfg.get("reward_risk_ratio") or 2.0)
    sl, tp = _sl_tp(side, entry, point, sl_pts, rr)
    comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]

    result = client.place_order(
        order_type=side,
        volume=TEST_VOLUME,
        sl=sl,
        tp=tp,
        comment=comment,
    )
    ok = bool(result.get("ok"))
    return {
        "ok": ok,
        "action": "test_open",
        "side": side,
        "volume": TEST_VOLUME,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "comment": comment,
        "result": result,
    }


def test_close_all(cfg: dict) -> dict[str, Any]:
    client = _client_from_cfg(cfg)
    comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]
    result = client.close_all(cfg["mt5_symbol"], comment=comment)
    return {"ok": bool(result.get("ok")), "action": "test_close_all", "result": result}
