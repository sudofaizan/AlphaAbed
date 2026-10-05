"""Capiffy trade API client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from app.capiffy.auth import capiffy_urlopen, get_valid_tokens

API_BASE = "https://api.capiffy.com"


def _request(method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    tokens = get_valid_tokens()
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {tokens.access_token}",
        "content-type": "application/json",
        "origin": "https://capiffy.com",
        "referer": "https://capiffy.com/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    if tokens.device_cid:
        headers["x-device-cid"] = tokens.device_cid
    if tokens.refresh_token:
        headers["Cookie"] = f"refreshToken={tokens.refresh_token}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with capiffy_urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {"ok": True}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Capiffy HTTP {exc.code}: {err_body[:500]}") from exc


def resolve_account_id(cfg: Optional[dict] = None) -> str:
    if cfg:
        acct = (cfg.get("capiffy_account_id") or "").strip()
        if acct:
            return acct
    tokens = get_valid_tokens()
    acct = tokens.account_id or os.environ.get("CAPIFFY_ACCOUNT_ID", "").strip()
    if not acct:
        raise ValueError("Capiffy account_id required (config or CAPIFFY_ACCOUNT_ID in .env)")
    return acct


def get_snapshot(account_id: Optional[str] = None, cfg: Optional[dict] = None) -> dict[str, Any]:
    acct = account_id or resolve_account_id(cfg)
    return _request("GET", f"/api/trade/snapshot/{acct}")


def get_open_positions(account_id: Optional[str] = None, cfg: Optional[dict] = None) -> list[dict[str, Any]]:
    snap = get_snapshot(account_id, cfg=cfg)
    return snap.get("data", {}).get("positions") or []


def close_position(position_id: str, account_id: Optional[str] = None) -> dict[str, Any]:
    _ = account_id
    return _request("DELETE", f"/api/trade/position/{position_id}")


def place_order(
    *,
    symbol: str,
    side: str,
    volume: float,
    order_type: str = "MARKET",
    price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    account_id: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> dict[str, Any]:
    acct = account_id or resolve_account_id(cfg)
    payload: dict[str, Any] = {
        "accountId": acct,
        "symbolTicker": symbol.upper(),
        "side": side.upper(),
        "volume": volume,
        "orderType": order_type.upper(),
    }
    if price is not None:
        payload["price"] = price
    if stop_loss is not None:
        payload["stopLoss"] = stop_loss
    if take_profit is not None:
        payload["takeProfit"] = take_profit
    return _request("POST", "/api/trade/order", payload)


def close_all_symbol(symbol: str, cfg: Optional[dict] = None) -> dict[str, Any]:
    sym = symbol.upper()
    positions = get_open_positions(cfg=cfg)
    closed: list[dict[str, Any]] = []
    errors: list[str] = []
    for pos in positions:
        pos_sym = str(pos.get("symbol") or pos.get("symbolTicker") or "").upper()
        if pos_sym and pos_sym != sym:
            continue
        pid = pos.get("id")
        if not pid:
            continue
        try:
            resp = close_position(str(pid))
            closed.append({"id": pid, "response": resp})
        except Exception as exc:
            errors.append(f"{pid}: {exc}")
    ok = not errors or bool(closed)
    return {"ok": ok, "closed": closed, "errors": errors}
