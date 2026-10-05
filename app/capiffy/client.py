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
        raise RuntimeError(
            f"Capiffy HTTP {exc.code} {method.upper()} {path}: {err_body[:500]}"
        ) from exc


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


def get_open_orders(account_id: Optional[str] = None, cfg: Optional[dict] = None) -> list[dict[str, Any]]:
    snap = get_snapshot(account_id, cfg=cfg)
    return snap.get("data", {}).get("orders") or []


def cancel_order(order_id: str, account_id: Optional[str] = None) -> dict[str, Any]:
    _ = account_id
    return _request("DELETE", f"/api/trade/order/{order_id}")


def modify_order(
    order_id: str,
    *,
    price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    volume: Optional[float] = None,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    _ = account_id
    body: dict[str, Any] = {}
    if price is not None:
        body["price"] = price
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if volume is not None:
        body["volume"] = volume
    if not body:
        raise ValueError("stop_loss, take_profit, price, or volume required")
    return _request("PATCH", f"/api/trade/order/{order_id}", body)


def modify_position(
    position_id: str,
    *,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    _ = account_id
    body: dict[str, Any] = {}
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if not body:
        raise ValueError("stop_loss or take_profit required")
    return _request("PATCH", f"/api/trade/position/{position_id}", body)


def close_position(position_id: str, account_id: Optional[str] = None) -> dict[str, Any]:
    _ = account_id
    return _request("DELETE", f"/api/trade/position/{position_id}")


def extract_order_id(response: dict[str, Any]) -> Optional[str]:
    if not response:
        return None
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("id", "orderId", "order_id"):
            if data.get(key):
                return str(data[key])
    for key in ("id", "orderId", "order_id"):
        if response.get(key):
            return str(response[key])
    return None


def extract_position_id(response: dict[str, Any]) -> Optional[str]:
    if not response:
        return None
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("id", "positionId", "position_id"):
            if data.get(key):
                return str(data[key])
        pos = data.get("position")
        if isinstance(pos, dict) and pos.get("id"):
            return str(pos["id"])
    for key in ("id", "positionId", "position_id"):
        if response.get(key):
            return str(response[key])
    return None


def _find_newest_position(
    symbol: str,
    side: str,
    volume: float,
    cfg: Optional[dict],
) -> Optional[str]:
    sym = symbol.upper()
    side_u = side.upper()
    positions = get_open_positions(cfg=cfg)
    for pos in reversed(positions):
        pos_sym = str(pos.get("symbol") or pos.get("symbolTicker") or "").upper()
        pos_side = str(pos.get("side") or "").upper()
        try:
            pos_vol = float(pos.get("volume") or 0)
        except (TypeError, ValueError):
            pos_vol = 0.0
        if pos_sym == sym and pos_side == side_u and abs(pos_vol - volume) < 1e-6:
            pid = pos.get("id")
            if pid:
                return str(pid)
    return None


def open_position(
    *,
    symbol: str,
    side: str,
    volume: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    account_id: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> dict[str, Any]:
    """Market open — Capiffy web app uses POST /api/trade/open (not /api/trade/order)."""
    acct = account_id or resolve_account_id(cfg)
    payload: dict[str, Any] = {
        "accountId": acct,
        "symbolTicker": symbol.upper(),
        "side": side.upper(),
        "volume": volume,
    }
    open_resp = _request("POST", "/api/trade/open", payload)
    out: dict[str, Any] = {"open": open_resp}

    if stop_loss is None and take_profit is None:
        return out

    pid = extract_position_id(open_resp) or _find_newest_position(
        symbol, side, volume, cfg
    )
    if not pid:
        out["sl_tp_skipped"] = "no position id after open — set SL/TP manually"
        return out

    try:
        out["modify"] = modify_position(
            pid, stop_loss=stop_loss, take_profit=take_profit
        )
        out["position_id"] = pid
    except Exception as exc:
        out["modify_error"] = str(exc)
        out["position_id"] = pid
    return out


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
    if order_type.upper() == "MARKET":
        return open_position(
            symbol=symbol,
            side=side,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            account_id=account_id,
            cfg=cfg,
        )
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
