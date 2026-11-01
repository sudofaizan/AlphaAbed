"""Wait for spot to enter a FROM range before opening (Telegram, no NOW)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.async_io import run_blocking
from app.config_store import load_config
from app.dual_trade import open_market_parallel
from app.lot_sizing import compute_trade_volumes, lot_profile_for_source
from app.mt5_accounts import list_enabled_mt5_accounts, mt5_client_for_account, primary_mt5_client
from app.state import state
from app.trade_dedupe import check_trade_cooldown, mark_trade_executed, reserve_trade_execution
from signals.classify import TradeSignal
from signals.trade_plan import TradePlan, build_trade_plan

log = logging.getLogger("alphaabed.range_wait")

_NOW = re.compile(r"\bNOW\b", re.I)


def normalize_range(lo: float | None, hi: float | None) -> tuple[float | None, float | None]:
    if lo is None or hi is None:
        return lo, hi
    return min(lo, hi), max(lo, hi)


def telegram_range_wait_needed(source: str, signal: TradeSignal, raw_text: str, cfg: dict) -> bool:
    if not cfg.get("range_wait_enabled", True):
        return False
    if (source or "").lower() != "telegram":
        return False
    if signal.entry_min is None or signal.entry_max is None:
        return False
    if _NOW.search(raw_text or ""):
        return False
    return True


def price_in_range(side: str, bid: float, ask: float, range_lo: float, range_hi: float) -> bool:
    side = side.lower()
    if side == "buy":
        return range_lo <= ask <= range_hi
    return range_lo <= bid <= range_hi


def distance_to_range_points(
    side: str, bid: float, ask: float, range_lo: float, range_hi: float, point: float
) -> tuple[float, str | None]:
    """
    Points from spot to nearest range boundary. Returns (points, where) where
    where is 'below' | 'above' | None if already inside.
    """
    if point <= 0:
        return 0.0, None
    if price_in_range(side, bid, ask, range_lo, range_hi):
        return 0.0, None
    main = side.lower()
    if main == "buy":
        ref = ask
        if ref < range_lo:
            return (range_lo - ref) / point, "below"
        if ref > range_hi:
            return (ref - range_hi) / point, "above"
    else:
        ref = bid
        if ref > range_hi:
            return (ref - range_hi) / point, "above"
        if ref < range_lo:
            return (range_lo - ref) / point, "below"
    return 0.0, None


def price_outside_range(side: str, bid: float, ask: float, range_lo: float, range_hi: float) -> str | None:
    """Return 'below' or 'above' if clearly outside; else None if inside."""
    if price_in_range(side, bid, ask, range_lo, range_hi):
        return None
    ref = ask if side == "buy" else bid
    if ref < range_lo:
        return "below"
    if ref > range_hi:
        return "above"
    return None


@dataclass
class RangeWatch:
    message_id: str
    source: str
    raw_text: str
    signal: TradeSignal
    range_lo: float
    range_hi: float
    started_at: float
    timeout_sec: float
    poll_sec: float
    fade_enabled: bool
    fade_opened: bool = False
    fade_software_tp: bool = False
    fade_tp_price: float | None = None
    row_snapshot: dict[str, Any] = field(default_factory=dict)


_watches: dict[str, RangeWatch] = {}
_watch_tasks: dict[str, asyncio.Task] = {}


def active_watches_snapshot() -> list[dict[str, Any]]:
    out = []
    now = time.time()
    for key, w in _watches.items():
        out.append(
            {
                "id": key,
                "message_id": w.message_id,
                "side": w.signal.side,
                "range_lo": w.range_lo,
                "range_hi": w.range_hi,
                "elapsed_sec": int(now - w.started_at),
                "timeout_sec": int(w.timeout_sec),
                "fade_opened": w.fade_opened,
            }
        )
    return out


def _watch_key(source: str, message_id: str) -> str:
    return f"{source}:{message_id}"


def cancel_watch(source: str, message_id: str) -> None:
    key = _watch_key(source, message_id)
    task = _watch_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()
    _watches.pop(key, None)


def cancel_all_watches() -> None:
    for key in list(_watches.keys()):
        src, mid = key.split(":", 1)
        cancel_watch(src, mid)


def start_range_watch(row: dict[str, Any], cfg: dict, signal: TradeSignal) -> dict[str, Any]:
    source = (row.get("source") or "telegram").lower()
    mid = str(row.get("message_id") or "")
    key = _watch_key(source, mid)
    if key in _watches:
        return {"action": "range_wait", "status": "already_watching", "message_id": mid}

    lo, hi = normalize_range(signal.entry_min, signal.entry_max)
    if lo is None or hi is None:
        return {"action": "skipped", "reason": "invalid range"}

    timeout = float(cfg.get("range_wait_timeout_sec") or 3600)
    poll = max(1.0, float(cfg.get("range_poll_sec") or 3))
    watch = RangeWatch(
        message_id=mid,
        source=source,
        raw_text=row.get("raw_text") or "",
        signal=signal,
        range_lo=lo,
        range_hi=hi,
        started_at=time.time(),
        timeout_sec=timeout,
        poll_sec=poll,
        fade_enabled=bool(cfg.get("range_fade_enabled")),
        row_snapshot=dict(row),
    )
    _watches[key] = watch
    return {
        "action": "range_wait",
        "status": "started",
        "message_id": mid,
        "range_lo": lo,
        "range_hi": hi,
        "timeout_sec": timeout,
        "side": signal.side,
    }


def _fade_comment_tag(cfg: dict) -> str:
    return ((cfg.get("mt5_trade_comment") or "ABD") + "F")[:31]


def _build_fade_plan(
    cfg: dict,
    *,
    main_side: str,
    where: str,
    bid: float,
    ask: float,
    point: float,
    range_lo: float,
    range_hi: float,
) -> tuple[TradePlan | None, bool, float | None]:
    """
    Counter-trade into the range before the main FROM fill.
    Returns (plan, software_tp, software_tp_price).
    software_tp: close fade when price touches range (MT5 TP invalid on wrong side).
    """
    sl_pts = float(cfg.get("default_sl_points") or 500)
    sl_dist = sl_pts * point
    main_side = main_side.lower()

    # Main BUY FROM range — fade with SELL into the zone
    if main_side == "buy" and where == "below":
        entry = bid
        sl = entry + sl_dist
        # TP at range lower bound — close via poll when ask >= range_lo
        return (
            TradePlan(
                side="sell",
                symbol="XAUUSD",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=None,
                risk_points=round(sl_dist, 2),
                reward_points=None,
                reward_risk_ratio=None,
                bid=bid,
                ask=ask,
                used_signal_tp=False,
                notes="fade sell → TP at range (software)",
            ),
            True,
            range_lo,
        )
    if main_side == "buy" and where == "above":
        entry = bid
        sl = entry + sl_dist
        tp = range_hi
        if tp >= entry:
            return None, False, None
        return (
            TradePlan(
                side="sell",
                symbol="XAUUSD",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                risk_points=round(sl_dist, 2),
                reward_points=round(entry - tp, 2),
                reward_risk_ratio=None,
                bid=bid,
                ask=ask,
                used_signal_tp=True,
                notes="fade sell → TP at range top",
            ),
            False,
            None,
        )

    # Main SELL FROM range — fade with BUY into the zone
    if main_side == "sell" and where == "above":
        entry = ask
        sl = entry - sl_dist
        return (
            TradePlan(
                side="buy",
                symbol="XAUUSD",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=None,
                risk_points=round(sl_dist, 2),
                reward_points=None,
                reward_risk_ratio=None,
                bid=bid,
                ask=ask,
                used_signal_tp=False,
                notes="fade buy → TP at range (software)",
            ),
            True,
            range_hi,
        )
    if main_side == "sell" and where == "below":
        entry = ask
        sl = entry - sl_dist
        tp = range_lo
        if tp <= entry:
            return None, False, None
        return (
            TradePlan(
                side="buy",
                symbol="XAUUSD",
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                risk_points=round(sl_dist, 2),
                reward_points=round(tp - entry, 2),
                reward_risk_ratio=None,
                bid=bid,
                ask=ask,
                used_signal_tp=True,
                notes="fade buy → TP at range bottom",
            ),
            False,
            None,
        )
    return None, False, None


def _close_fade_positions_sync(cfg: dict) -> dict[str, Any]:
    """Close MT5 legs opened with fade comment tag (…F)."""
    tag = _fade_comment_tag(cfg)
    out: list[Any] = []
    for acc in list_enabled_mt5_accounts(cfg):
        client = mt5_client_for_account(acc)
        sym = acc.get("symbol") or cfg["mt5_symbol"]
        resp = client.get_positions(symbol=sym)
        for pos in resp.get("positions") or []:
            cmt = (pos.get("comment") or "").strip()
            if tag not in cmt and not cmt.endswith("F"):
                continue
            ticket = pos.get("ticket")
            if not ticket:
                continue
            out.append(
                client._request("POST", "/closePositions", body={"ticket": ticket, "comment": tag})
            )
    return {"ok": True, "closed": len(out), "results": out}


def _fade_volume(cfg: dict, source: str, fraction: float) -> float:
    prof = lot_profile_for_source(cfg, source)
    base = prof["volume"]
    if prof["lot_mode"] == "risk_usd":
        base = max(base, 0.01)
    vol = max(0.01, round(base * fraction, 3))
    return vol


def _execute_open_sync(
    cfg: dict,
    row: dict[str, Any],
    signal: TradeSignal,
    bid: float,
    ask: float,
    point: float,
    *,
    volume_scale: float = 1.0,
    plan_override: TradePlan | None = None,
    comment_suffix: str = "",
) -> dict[str, Any]:
    source = (row.get("source") or "telegram").lower()
    default_sl = float(cfg["default_sl_points"]) if signal.sl is None else None
    prefer_tp = bool(cfg.get("prefer_signal_tp")) or (
        source == "whatsapp" and signal.tp is not None
    )
    plan = plan_override or build_trade_plan(
        signal,
        bid=bid,
        ask=ask,
        reward_risk_ratio=float(cfg["reward_risk_ratio"]),
        prefer_signal_tp=prefer_tp,
        default_sl_points=default_sl,
        point=point,
    )
    if not plan or plan.sl is None:
        return {"ok": False, "error": "could not build trade plan"}

    mt5_vol, cap_vol, sizing_meta = compute_trade_volumes(
        cfg, source=source, signal=signal, plan=plan, point=point
    )
    if volume_scale != 1.0:
        mt5_vol = max(0.01, round(mt5_vol * volume_scale, 3))
        cap_vol = max(0.01, round(cap_vol * volume_scale, 3))
        sizing_meta = {**sizing_meta, "volume_scale": volume_scale}

    if source == "whatsapp":
        comment = (cfg.get("whatsapp_trade_comment") or "WASIG").strip()[:31]
    else:
        comment = (cfg.get("mt5_trade_comment") or "ABD").strip()[:31]
    if comment_suffix:
        comment = (comment + comment_suffix)[:31]

    result = open_market_parallel(
        cfg,
        plan,
        mt5_volume=mt5_vol,
        capiffy_volume=cap_vol,
        mt5_comment=comment,
    )
    return {
        "ok": True,
        "action": "open",
        "plan": plan.__dict__,
        "sizing": sizing_meta,
        "result": result,
        "message_id": row.get("message_id"),
        "source": source,
    }


async def _run_watch(key: str, stop_event: asyncio.Event) -> None:
    watch = _watches.get(key)
    if not watch:
        return
    log.info(
        "Range watch %s %s %.2f-%.2f timeout=%ss",
        watch.message_id,
        watch.signal.side,
        watch.range_lo,
        watch.range_hi,
        watch.timeout_sec,
    )
    state.push_event(
        "range_wait",
        f"Waiting {watch.signal.side} {watch.range_lo}-{watch.range_hi} (msg {watch.message_id})",
    )

    try:
        while not stop_event.is_set():
            if time.time() - watch.started_at > watch.timeout_sec:
                log.info("Range watch timeout %s", watch.message_id)
                state.push_event("range_wait", f"Timed out waiting for range (msg {watch.message_id})")
                break

            cfg = load_config()
            if not cfg.get("auto_trade"):
                break

            client = primary_mt5_client(cfg)
            price = await run_blocking(client.get_price)
            if not price.get("ok"):
                await _sleep(stop_event, watch.poll_sec)
                continue

            bid = float(price["bid"])
            ask = float(price["ask"])
            point = float(price.get("point") or 0.01)
            side = watch.signal.side
            dist_pts, where = distance_to_range_points(
                side, bid, ask, watch.range_lo, watch.range_hi, point
            )
            min_dist = float(cfg.get("range_fade_min_distance_points") or 2000)

            if watch.fade_software_tp and watch.fade_opened and watch.fade_tp_price is not None:
                hit = False
                if watch.signal.side == "buy" and ask >= watch.fade_tp_price:
                    hit = True
                if watch.signal.side == "sell" and bid <= watch.fade_tp_price:
                    hit = True
                if hit:
                    closed = await run_blocking(_close_fade_positions_sync, cfg)
                    watch.fade_opened = False
                    watch.fade_software_tp = False
                    state.push_event(
                        "range_wait",
                        f"Fade TP at range {watch.fade_tp_price} (msg {watch.message_id})",
                        detail=closed,
                    )

            if watch.fade_enabled and not watch.fade_opened and where and dist_pts > min_dist:
                fade_plan, soft_tp, tp_price = _build_fade_plan(
                    cfg,
                    main_side=side,
                    where=where,
                    bid=bid,
                    ask=ask,
                    point=point,
                    range_lo=watch.range_lo,
                    range_hi=watch.range_hi,
                )
                if fade_plan and fade_plan.sl is not None:
                    frac = float(cfg.get("range_fade_lot_fraction") or 0.5)
                    fade_sig = TradeSignal(
                        side=fade_plan.side,
                        symbol=watch.signal.symbol,
                        sl=fade_plan.sl,
                        tp=fade_plan.tp,
                        market=True,
                    )
                    trade = await run_blocking(
                        _execute_open_sync,
                        cfg,
                        watch.row_snapshot,
                        fade_sig,
                        bid,
                        ask,
                        point,
                        volume_scale=frac,
                        plan_override=fade_plan,
                        comment_suffix="F",
                    )
                    watch.fade_opened = True
                    watch.fade_software_tp = soft_tp
                    watch.fade_tp_price = tp_price
                    tp_note = (
                        f"TP@{tp_price} (software)"
                        if soft_tp
                        else f"TP@{fade_plan.tp}"
                    )
                    state.push_event(
                        "trade",
                        f"Range fade {fade_plan.side} 1/2 lot {tp_note} msg {watch.message_id}",
                        trade=trade,
                    )
                    log.info("Range fade opened for %s: %s", watch.message_id, trade)

            if price_in_range(side, bid, ask, watch.range_lo, watch.range_hi):
                if watch.fade_opened:
                    await run_blocking(_close_fade_positions_sync, cfg)
                    watch.fade_opened = False
                ok_cd, cd_reason = check_trade_cooldown(int(cfg.get("trade_cooldown_sec") or 300))
                if not ok_cd:
                    state.push_event("range_wait", f"In range but cooldown: {cd_reason}")
                    break
                ok_res, dup = reserve_trade_execution(watch.source, watch.message_id)
                if not ok_res:
                    state.push_event("range_wait", f"In range but duplicate: {dup}")
                    break

                trade = await run_blocking(
                    _execute_open_sync,
                    cfg,
                    watch.row_snapshot,
                    watch.signal,
                    bid,
                    ask,
                    point,
                )
                mark_trade_executed()
                state.push_event(
                    "trade",
                    f"Range fill {side} @ {ask if side == 'buy' else bid} msg {watch.message_id}",
                    trade=trade,
                )
                log.info("Range main open %s: %s", watch.message_id, trade.get("result"))
                break

            await _sleep(stop_event, watch.poll_sec)
    except asyncio.CancelledError:
        log.info("Range watch cancelled %s", watch.message_id)
        raise
    finally:
        _watches.pop(key, None)
        _watch_tasks.pop(key, None)


async def _sleep(stop_event: asyncio.Event, sec: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=sec)
    except asyncio.TimeoutError:
        pass


def schedule_range_watch(row: dict[str, Any], cfg: dict, signal: TradeSignal, stop_event: asyncio.Event) -> dict[str, Any]:
    out = start_range_watch(row, cfg, signal)
    if out.get("status") != "started":
        return out
    key = _watch_key((row.get("source") or "telegram").lower(), str(row.get("message_id")))
    task = asyncio.create_task(_run_watch(key, stop_event))
    _watch_tasks[key] = task
    return out


async def range_watch_maintenance_loop(stop_event: asyncio.Event) -> None:
    """Keep module alive; watches are per-signal tasks."""
    while not stop_event.is_set():
        await _sleep(stop_event, 60)
