"""Fetch MT5 deal history (ABD / WASIG) for dashboard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.datetime_util import format_card_time_ist
from app.mt5_accounts import list_enabled_mt5_accounts, mt5_client_for_account
from app.test_trade import TEST_VOLUME_MT5

SIGNAL_COMMENTS = frozenset({"ABD", "WASIG"})


def _volume_is_test_lot(volume: Any) -> bool:
    try:
        v = float(volume)
    except (TypeError, ValueError):
        return False
    return abs(v - TEST_VOLUME_MT5) < 1e-6


def _deal_profit(deal: dict[str, Any]) -> float:
    for key in ("net", "profit"):
        if deal.get(key) is not None:
            try:
                return float(deal[key])
            except (TypeError, ValueError):
                pass
    return 0.0


def _comment_matches(comment: str | None) -> bool:
    c = (comment or "").strip()
    if not c:
        return False
    if c in SIGNAL_COMMENTS:
        return True
    for tag in SIGNAL_COMMENTS:
        if c.startswith(tag):
            return True
    return False


def _signal_tag_from_comment(comment: str | None) -> str:
    c = (comment or "").strip()
    if c.startswith("WASIG") or c == "WASIG":
        return "WASIG"
    if c.startswith("ABD") or c == "ABD":
        return "ABD"
    return c[:8] if c else "—"


def _linked_signal_trades(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    MT5 often clears or replaces comment on OUT deals ([sl …], [tp …], empty).
    Link OUT closes to positions opened with IN deals tagged ABD / WASIG.
    """
    open_meta: dict[Any, dict[str, Any]] = {}
    for d in deals:
        if (d.get("entry") or "").lower() != "in":
            continue
        if not _comment_matches(d.get("comment")):
            continue
        if _volume_is_test_lot(d.get("volume")):
            continue
        pid = d.get("position_id")
        if pid is None:
            continue
        open_meta[pid] = {
            "comment": _signal_tag_from_comment(d.get("comment")),
            "open_time": d.get("time"),
            "open_type": d.get("type"),
            "volume": d.get("volume"),
            "symbol": d.get("symbol"),
        }

    closed: list[dict[str, Any]] = []
    for d in deals:
        if (d.get("entry") or "").lower() != "out":
            continue
        pid = d.get("position_id")
        meta = open_meta.get(pid)
        if not meta:
            continue
        closed.append({**d, "_signal_meta": meta, "_signal_comment": meta["comment"]})
    return closed


def _normalize_deal(deal: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    pnl = _deal_profit(deal)
    meta = deal.get("_signal_meta") or {}
    tag = deal.get("_signal_comment") or _signal_tag_from_comment(deal.get("comment"))
    t = deal.get("time") or deal.get("time_msc")
    return {
        "ticket": deal.get("ticket"),
        "position_id": deal.get("position_id"),
        "time": t,
        "time_ist": format_card_time_ist(t),
        "symbol": deal.get("symbol") or meta.get("symbol"),
        "type": deal.get("type") or meta.get("open_type"),
        "volume": deal.get("volume") or meta.get("volume"),
        "price": deal.get("price"),
        "profit": deal.get("profit"),
        "net": deal.get("net", pnl),
        "pnl": pnl,
        "comment": tag,
        "account_id": account.get("id"),
        "account_label": account.get("label") or account.get("id"),
        "win": pnl > 0,
        "loss": pnl < 0,
    }


def fetch_account_history(account: dict[str, Any], *, days: int = 30) -> dict[str, Any]:
    client = mt5_client_for_account(account)
    client.cfg.timeout = max(int(client.cfg.timeout), 45)
    resp = client.get_history(days=days, closed_only=False, limit=10000)
    if not resp.get("ok"):
        return {
            "ok": False,
            "account_id": account.get("id"),
            "label": account.get("label"),
            "error": resp.get("error") or "getHistory failed",
        }
    raw = resp.get("deals") or []
    linked = _linked_signal_trades(raw)
    deals = [_normalize_deal(d, account) for d in linked]
    return {
        "ok": True,
        "account_id": account.get("id"),
        "label": account.get("label"),
        "raw_count": resp.get("count"),
        "deals": deals,
    }


def summarize_deals(deals: list[dict[str, Any]]) -> dict[str, Any]:
    if not deals:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate_pct": None,
            "total_profit": 0.0,
        }
    wins = sum(1 for d in deals if d.get("win"))
    losses = sum(1 for d in deals if d.get("loss"))
    breakeven = len(deals) - wins - losses
    decided = wins + losses
    win_rate = round(100.0 * wins / decided, 1) if decided else None
    total = round(sum(float(d.get("pnl") or 0) for d in deals), 2)
    return {
        "total_trades": len(deals),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate_pct": win_rate,
        "total_profit": total,
    }


def fetch_past_trades(cfg: dict, *, days: int = 30) -> dict[str, Any]:
    accounts = list_enabled_mt5_accounts(cfg)
    if not accounts:
        return {"ok": False, "error": "No MT5 accounts configured", "deals": [], "summary": summarize_deals([])}

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(len(accounts), 1)) as pool:
        futures = [pool.submit(fetch_account_history, acc, days=days) for acc in accounts]
        for fut in futures:
            results.append(fut.result())

    all_deals: list[dict[str, Any]] = []
    errors: list[str] = []
    for r in results:
        if r.get("ok"):
            all_deals.extend(r.get("deals") or [])
        else:
            errors.append(f"{r.get('label') or r.get('account_id')}: {r.get('error')}")

    all_deals.sort(key=lambda d: d.get("time") or "", reverse=True)
    summary = summarize_deals(all_deals)
    return {
        "ok": not errors or bool(all_deals),
        "days": days,
        "comments": sorted(SIGNAL_COMMENTS),
        "deals": all_deals,
        "summary": summary,
        "accounts": results,
        "errors": errors,
        "note": (
            "Closed legs linked to opens with comment ABD/WASIG; "
            f"excludes {TEST_VOLUME_MT5} lot test opens; "
            "OUT rows often have empty or [sl]/[tp] comments."
        ),
    }
