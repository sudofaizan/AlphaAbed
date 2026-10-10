"""Poll configurable WhatsApp message feed (JSON /latest)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import timezone
from typing import Any

from app.datetime_util import format_message_time_ist
from app.whatsapp_state import load_seen_ids, mark_seen, mark_seen_many
from signals.whatsapp_classify import classify_whatsapp_text, format_whatsapp_signal_line

log = logging.getLogger("alphaabed.whatsapp")

DEFAULT_TIMEOUT = 8


def _fetch_url(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {body[:200]}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e.reason)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"invalid JSON: {e}"}


def test_whatsapp_feed(cfg: dict) -> dict[str, Any]:
    url = (cfg.get("whatsapp_messages_url") or "").strip()
    if not url:
        return {"ok": False, "error": "Set WhatsApp messages URL in Settings"}
    payload = _fetch_url(url)
    if payload.get("ok") is False and payload.get("error"):
        return {"ok": False, "error": payload["error"]}
    messages = payload.get("messages") or []
    channel = payload.get("channel") or payload.get("channelId") or "—"
    latest = messages[0] if messages else None
    preview = ""
    if latest:
        preview = (latest.get("message") or "")[:120]
    return {
        "ok": True,
        "channel": channel,
        "count": payload.get("count") or len(messages),
        "latest_message_id": latest.get("messageId") if latest else None,
        "preview": preview,
    }


def _msg_to_row(msg: dict[str, Any]) -> dict[str, Any]:
    body = (msg.get("message") or "").strip()
    mid = str(msg.get("messageId") or "")
    when = msg.get("timeUtc") or ""
    parsed = classify_whatsapp_text(body)
    when_dt = None
    if when:
        try:
            when_dt = __import__("datetime").datetime.fromisoformat(
                str(when).replace("Z", "+00:00")
            )
            if when_dt.tzinfo is None:
                when_dt = when_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            when_dt = None
    row: dict[str, Any] = {
        "message_id": mid,
        "source": "whatsapp",
        "date": when,
        "date_ist": format_message_time_ist(when_dt) if when_dt else when,
        "kind": parsed.kind,
        "summary": format_whatsapp_signal_line(parsed, mid),
        "raw_text": body,
        "reason": parsed.reason,
    }
    if parsed.signal:
        s = parsed.signal
        row["signal"] = {
            "side": s.side,
            "symbol": s.symbol,
            "entry": s.entry,
            "sl": s.sl,
            "tp": s.tp,
            "tp_levels": getattr(s, "tp_levels", None),
            "market": True,
        }
    return row


def poll_new_whatsapp_messages(cfg: dict, *, bootstrap: bool = False) -> dict[str, Any]:
    """
    Return new rows oldest-first. Marks IDs seen after successful parse path.
    bootstrap=True: mark all current feed IDs seen without returning rows (first deploy).
    """
    url = (cfg.get("whatsapp_messages_url") or "").strip()
    if not url:
        return {"ok": False, "error": "whatsapp_messages_url not set", "rows": []}

    payload = _fetch_url(url)
    if payload.get("ok") is False and payload.get("error"):
        return {"ok": False, "error": payload["error"], "rows": []}

    messages = list(payload.get("messages") or [])
    seen = load_seen_ids()

    if bootstrap and messages:
        mark_seen_many([str(m.get("messageId")) for m in messages if m.get("messageId")])
        return {"ok": True, "bootstrapped": len(messages), "rows": []}

    new_msgs = [m for m in messages if str(m.get("messageId") or "") not in seen]
    new_msgs.sort(key=lambda m: m.get("timeUtc") or m.get("timestamp") or "")

    rows = [_msg_to_row(m) for m in new_msgs]
    for m in new_msgs:
        mid = str(m.get("messageId") or "")
        if mid:
            mark_seen(mid)

    return {
        "ok": True,
        "channel": payload.get("channel"),
        "fetched": len(messages),
        "new_count": len(rows),
        "rows": rows,
    }


def fetch_whatsapp_history_rows(cfg: dict) -> list[dict[str, Any]]:
    """All open signals from the latest feed batch (for dashboard history, no dedupe)."""
    url = (cfg.get("whatsapp_messages_url") or "").strip()
    if not url:
        return []
    payload = _fetch_url(url)
    if payload.get("ok") is False and payload.get("error"):
        return []
    messages = list(payload.get("messages") or [])
    rows: list[dict[str, Any]] = []
    for msg in messages:
        row = _msg_to_row(msg)
        if row.get("kind") == "open_signal":
            rows.append(row)
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows
