"""Fetch MT5 deal history (ABD / WASIG) for dashboard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.datetime_util import format_card_time_ist
from app.mt5_accounts import list_enabled_mt5_accounts, mt5_client_for_account

SIGNAL_COMMENTS = frozenset({"ABD", "WASIG"})


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
    # MT5 may append suffixes; match prefix
    for tag in SIGNAL_COMMENTS:
        if c.startswith(tag):
            return True
    return False


def _normalize_deal(deal: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    pnl = _deal_profit(deal)
    t = deal.get("time") or deal.get("time_msc")
    return {
        "ticket": deal.get("ticket"),
        "position_id": deal.get("position_id"),
        "time": t,
        "time_ist": format_card_time_ist(t),
        "symbol": deal.get("symbol"),
        "type": deal.get("type"),
        "volume": deal.get("volume"),
        "price": deal.get("price"),
        "profit": deal.get("profit"),
        "net": deal.get("net", pnl),
        "pnl": pnl,
        "comment": (deal.get("comment") or "").strip(),
        "account_id": account.get("id"),
        "account_label": account.get("label") or account.get("id"),
        "win": pnl > 0,
        "loss": pnl < 0,
    }


def fetch_account_history(account: dict[str, Any], *, days: int = 30) -> dict[str, Any]:
    client = mt5_client_for_account(account)
    client.cfg.timeout = max(int(client.cfg.timeout), 45)
    resp = client.get_history(days=days, closed_only=True, limit=10000)
    if not resp.get("ok"):
        return {
            "ok": False,
            "account_id": account.get("id"),
            "label": account.get("label"),
            "error": resp.get("error") or "getHistory failed",
        }
    deals = [
        _normalize_deal(d, account)
        for d in (resp.get("deals") or [])
        if _comment_matches(d.get("comment"))
    ]
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
    }
