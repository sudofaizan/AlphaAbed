"""Send parsed signals to your MT5 HTTP API."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from signals.classify import TradeSignal

log = logging.getLogger("alphaabed.mt5")


def _api_url(path: str) -> str:
    base = os.getenv("MT5_API_URL", "http://127.0.0.1:8080").rstrip("/")
    return f"{base}{path}"


def _post(path: str, payload: dict) -> dict:
    url = _api_url(path)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    api_key = os.getenv("MT5_API_KEY", "").strip()
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def execute_open(signal: TradeSignal, *, message_id: int) -> dict:
    payload = {
        "action": "open",
        "side": signal.side,
        "symbol": signal.symbol,
        "entry": signal.entry,
        "entry_min": signal.entry_min,
        "entry_max": signal.entry_max,
        "sl": signal.sl,
        "tp": signal.tp,
        "market": signal.market,
        "source": "telegram",
        "source_message_id": message_id,
    }
    path = os.getenv("MT5_OPEN_PATH", "/order")
    log.info("MT5 open payload: %s", payload)
    return _post(path, payload)


def execute_close_all(*, message_id: int) -> dict:
    payload = {
        "action": "close_all",
        "source": "telegram",
        "source_message_id": message_id,
    }
    path = os.getenv("MT5_CLOSE_PATH", "/order")
    log.info("MT5 close_all payload: %s", payload)
    return _post(path, payload)


def execute_partial_close(*, message_id: int) -> dict:
    payload = {
        "action": "partial_close",
        "source": "telegram",
        "source_message_id": message_id,
    }
    path = os.getenv("MT5_CLOSE_PATH", "/order")
    return _post(path, payload)


def dispatch_signal(
    kind: str,
    signal: TradeSignal | None,
    *,
    message_id: int,
    dry_run: bool,
) -> None:
    if dry_run:
        log.info("DRY_RUN: would dispatch kind=%s signal=%s id=%s", kind, signal, message_id)
        return

    try:
        if kind == "open_signal" and signal:
            execute_open(signal, message_id=message_id)
        elif kind == "close_all":
            execute_close_all(message_id=message_id)
        elif kind == "partial_close":
            execute_partial_close(message_id=message_id)
        else:
            log.info("No MT5 action for kind=%s", kind)
    except urllib.error.URLError as e:
        log.error("MT5 API error: %s", e)
