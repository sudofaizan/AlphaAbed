"""Execute MT5 and Capiffy legs in parallel (not sequential)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from app.capiffy import client as capiffy_client
from app.news_blackout import capiffy_news_blackout
from signals.alphafx_client import AlphaFxClient, AlphaFxConfig
from signals.trade_plan import TradePlan

log = logging.getLogger("alphaabed.dual_trade")


def capiffy_symbol_from_cfg(cfg: dict) -> str:
    sym = (cfg.get("capiffy_symbol") or "").strip()
    if sym:
        return sym.upper()
    mt5 = (cfg.get("mt5_symbol") or "XAUUSD").upper()
    for suffix in (".PR", ".C", ".M", ".I"):
        if mt5.endswith(suffix):
            return mt5[: -len(suffix)]
    return mt5.split(".")[0]


def _run_parallel(jobs: list[tuple[str, Callable[[], Any]]]) -> dict[str, Any]:
    if not jobs:
        return {}
    if len(jobs) == 1:
        name, fn = jobs[0]
        try:
            return {name: {"ok": True, "result": fn()}}
        except Exception as exc:
            log.exception("dual trade %s failed", name)
            return {name: {"ok": False, "error": str(exc)}}

    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs}
        for name, fut in futures.items():
            try:
                out[name] = {"ok": True, "result": fut.result()}
            except Exception as exc:
                log.exception("dual trade %s failed", name)
                out[name] = {"ok": False, "error": str(exc)}
    return out


def mt5_client_from_cfg(cfg: dict) -> AlphaFxClient:
    return AlphaFxClient(
        AlphaFxConfig(
            base_url=cfg["mt5_base_url"],
            api_key=cfg["mt5_api_key"],
            symbol=cfg["mt5_symbol"],
        )
    )


def should_trade_mt5(cfg: dict) -> bool:
    return bool(cfg.get("trade_mt5", True))


def should_trade_capiffy(cfg: dict) -> bool:
    return bool(cfg.get("capiffy_enabled")) and bool(cfg.get("trade_capiffy"))


def open_market_parallel(
    cfg: dict,
    plan: TradePlan,
    *,
    mt5_volume: Optional[float] = None,
    capiffy_volume: Optional[float] = None,
) -> dict[str, Any]:
    comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]
    mt5_vol = float(mt5_volume if mt5_volume is not None else cfg["volume"])
    cap_vol = float(
        capiffy_volume if capiffy_volume is not None else cfg.get("capiffy_volume") or mt5_vol
    )
    cap_sym = capiffy_symbol_from_cfg(cfg)
    side_cap = "BUY" if plan.side == "buy" else "SELL"

    jobs: list[tuple[str, Callable[[], Any]]] = []
    legs: dict[str, Any] = {}

    if should_trade_mt5(cfg):

        def _mt5() -> Any:
            client = mt5_client_from_cfg(cfg)
            return client.place_order(
                order_type=plan.side,
                volume=mt5_vol,
                sl=plan.sl,
                tp=plan.tp,
                comment=comment,
            )

        jobs.append(("mt5", _mt5))

    cap_blocked = False
    cap_block_reason = ""
    if should_trade_capiffy(cfg):
        blocked, reason, _ev = capiffy_news_blackout(cfg)
        if blocked:
            cap_blocked = True
            cap_block_reason = reason
            legs["capiffy"] = {
                "ok": False,
                "skipped": True,
                "news_blackout": True,
                "error": reason,
            }
        else:

            def _cap() -> Any:
                return capiffy_client.open_position(
                    symbol=cap_sym,
                    side=side_cap,
                    volume=cap_vol,
                    stop_loss=plan.sl,
                    take_profit=plan.tp,
                    cfg=cfg,
                )

            jobs.append(("capiffy", _cap))

    parallel = _run_parallel(jobs)
    legs.update(parallel)
    ok_parts = [leg.get("ok") for leg in legs.values() if not leg.get("skipped")]
    ok = all(ok_parts) if ok_parts else (not jobs and not cap_blocked)
    if cap_blocked and legs.get("mt5", {}).get("ok"):
        ok = True
    out: dict[str, Any] = {"ok": ok, "legs": legs, "plan": plan.__dict__}
    if cap_blocked:
        out["capiffy_news_blackout"] = cap_block_reason
    return out


def close_all_parallel(cfg: dict) -> dict[str, Any]:
    """Close MT5 only — Capiffy positions must be closed manually on capiffy.com."""
    comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]
    jobs: list[tuple[str, Callable[[], Any]]] = []
    capiffy_note: Optional[str] = None

    if should_trade_capiffy(cfg):
        capiffy_note = "Capiffy close skipped (XAUBeast opens only; close on Capiffy UI)"

    if should_trade_mt5(cfg):

        def _mt5() -> Any:
            return mt5_client_from_cfg(cfg).close_all(cfg["mt5_symbol"], comment=comment)

        jobs.append(("mt5", _mt5))

    legs = _run_parallel(jobs)
    ok = all(leg.get("ok") for leg in legs.values()) if legs else False
    out: dict[str, Any] = {"ok": ok, "legs": legs}
    if capiffy_note:
        out["capiffy_note"] = capiffy_note
    return out


def partial_close_mt5(cfg: dict, volume: float) -> dict[str, Any]:
    comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]
    return mt5_client_from_cfg(cfg).close_partial(cfg["mt5_symbol"], volume, comment=comment)


def test_capiffy_connection(cfg: dict) -> dict[str, Any]:
    from app.capiffy.auth import get_valid_tokens

    try:
        tokens = get_valid_tokens()
        snap = capiffy_client.get_snapshot(cfg=cfg)
        data = snap.get("data") or {}
        balance = data.get("balance") or data.get("equity")
        positions = data.get("positions") or []
        return {
            "ok": True,
            "access_expires_in": tokens.access_expires_in(),
            "account_id": capiffy_client.resolve_account_id(cfg),
            "balance": balance,
            "open_positions": len(positions),
            "snapshot_keys": list(data.keys())[:20],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
