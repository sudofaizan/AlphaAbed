"""HTTP client for AlphaFX MT5 VPS API (see API_DOCUMENTATION.md)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class AlphaFxConfig:
    base_url: str = "http://15.135.71.95:8080"
    api_key: str = "alphafx"
    symbol: str = "XAUUSD.pr"
    timeout: int = 12

    @property
    def base(self) -> str:
        return self.base_url.rstrip("/")


class AlphaFxClient:
    def __init__(self, cfg: AlphaFxConfig) -> None:
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["X-API-Key"] = self.cfg.api_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        body: dict | None = None,
        auth: bool = True,
    ) -> dict:
        url = f"{self.cfg.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None
        headers = self._headers() if auth else {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": raw or str(e)}
            payload.setdefault("ok", False)
            payload["http_status"] = e.code
            return payload
        except urllib.error.URLError as e:
            return {"ok": False, "error": str(e.reason)}

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    def account_health(self) -> dict:
        return self._request("GET", "/getAccountHealth")

    def get_price(self, symbol: str | None = None) -> dict:
        sym = symbol or self.cfg.symbol
        return self._request("GET", "/getPrice", query={"symbol": sym})

    def get_upcoming_news(
        self,
        *,
        hours: int = 72,
        impact: str = "High",
        currency: str | None = "USD",
    ) -> dict:
        query: dict[str, str | int] = {"hours": hours, "impact": impact}
        if currency:
            query["currency"] = currency
        return self._request("GET", "/getUpcomingNews", query=query)

    def place_order(
        self,
        *,
        order_type: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        price: float | None = None,
        comment: str = "ABD",
        magic: int | None = None,
    ) -> dict:
        payload: dict = {
            "symbol": self.cfg.symbol,
            "type": order_type,
            "volume": volume,
            "comment": comment,
        }
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        if price is not None:
            payload["price"] = price
        if magic is not None:
            payload["magic"] = magic
        return self._request("POST", "/placeOrder", body=payload)

    def close_all(self, symbol: str | None = None, *, comment: str = "ABD") -> dict:
        body: dict = {"comment": comment}
        if symbol:
            body["symbol"] = symbol
        return self._request("POST", "/closePositions", body=body)

    def close_partial(
        self,
        symbol: str | None = None,
        volume: float | None = None,
        *,
        comment: str = "ABD",
    ) -> dict:
        body: dict = {"symbol": symbol or self.cfg.symbol, "comment": comment}
        if volume is not None:
            body["volume"] = volume
        return self._request("POST", "/closePositions", body=body)
