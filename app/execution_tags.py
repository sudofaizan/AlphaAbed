"""Build UI-friendly MT5 / Capiffy execution status for signal history."""

from __future__ import annotations

from typing import Any, Optional


def _mt5_result_ok(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if "ok" in payload:
        return bool(payload.get("ok"))
    return True


def _mt5_error_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    for key in ("error", "message", "reason"):
        if payload.get(key):
            return str(payload[key])
    return str(payload)[:200]


def _capiffy_open_ok(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("modify_error"):
        return True
    open_part = payload.get("open")
    if isinstance(open_part, dict):
        if open_part.get("success") is False:
            return False
        err = open_part.get("error")
        if isinstance(err, dict) and err.get("message"):
            return False
    return True


def _capiffy_error_text(leg: dict[str, Any], payload: Any) -> str:
    if leg.get("error"):
        return str(leg["error"])
    if isinstance(payload, dict):
        if payload.get("modify_error"):
            return f"Open OK; SL/TP: {payload['modify_error']}"
        open_part = payload.get("open")
        if isinstance(open_part, dict):
            err = open_part.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
    return "Capiffy open failed"


def _tag(platform_id: str, label: str, status: str, detail: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": platform_id, "label": label, "status": status}
    if detail:
        out["detail"] = detail
    return out


def summarize_trade_execution(trade: dict[str, Any], cfg: dict) -> dict[str, Any]:
    """Tags for lower-right of signal card: MT5 / CAPIFY success or errors."""
    action = trade.get("action", "")
    capiffy_on = bool(cfg.get("capiffy_enabled")) and bool(cfg.get("trade_capiffy"))
    mt5_on = bool(cfg.get("trade_mt5", True))

    if action == "skipped":
        return {
            "processed": False,
            "action": action,
            "tags": [],
            "errors": [str(trade.get("reason") or "skipped")],
        }

    if action == "error":
        return {
            "processed": False,
            "action": action,
            "tags": [],
            "errors": [str(trade.get("reason") or "error")],
        }

    tags: list[dict[str, Any]] = []
    errors: list[str] = []

    if action == "open":
        bundle = trade.get("result") or {}
        legs = bundle.get("legs") or {}

        if mt5_on:
            leg = legs.get("mt5")
            if leg and leg.get("ok") and _mt5_result_ok(leg.get("result")):
                tags.append(_tag("mt5", "MT5", "success"))
            elif leg:
                msg = leg.get("error") or _mt5_error_text(leg.get("result"))
                tags.append(_tag("mt5", "MT5", "failed", msg))
                errors.append(f"MT5: {msg}")
            else:
                tags.append(_tag("mt5", "MT5", "failed", "no response"))
                errors.append("MT5: no response")

        if capiffy_on:
            leg = legs.get("capiffy")
            if leg and leg.get("news_blackout"):
                msg = leg.get("error") or "Red-folder news window"
                tags.append(_tag("capiffy", "CAPIFY", "skipped", msg))
                errors.append(msg)
            elif leg and leg.get("ok") and _capiffy_open_ok(leg.get("result")):
                tags.append(_tag("capiffy", "CAPIFY", "success"))
                res = leg.get("result") or {}
                if res.get("modify_error"):
                    errors.append(f"CAPIFY SL/TP: {res['modify_error']}")
            elif leg:
                msg = _capiffy_error_text(leg, leg.get("result"))
                tags.append(_tag("capiffy", "CAPIFY", "failed", msg))
                errors.append(f"CAPIFY: {msg}")
            else:
                tags.append(_tag("capiffy", "CAPIFY", "failed", "no response"))
                errors.append("CAPIFY: no response")

        processed = bool(tags) and all(t["status"] in ("success", "skipped") for t in tags)
        return {"processed": processed, "action": action, "tags": tags, "errors": errors}

    if action in ("close_all", "partial_close"):
        # Capiffy: open-only — no close tag on close_all (MT5 only).
        if action == "close_all":
            bundle = trade.get("result") or {}
            legs = bundle.get("legs") or {}
            leg = legs.get("mt5")
            if mt5_on:
                if leg and leg.get("ok") and _mt5_result_ok(leg.get("result")):
                    tags.insert(0, _tag("mt5", "MT5", "success"))
                elif leg:
                    msg = leg.get("error") or _mt5_error_text(leg.get("result"))
                    tags.insert(0, _tag("mt5", "MT5", "failed", msg))
                    errors.append(f"MT5: {msg}")
        else:
            res = trade.get("result")
            if mt5_on:
                if _mt5_result_ok(res):
                    tags.insert(0, _tag("mt5", "MT5", "success"))
                else:
                    msg = _mt5_error_text(res)
                    tags.insert(0, _tag("mt5", "MT5", "failed", msg))
                    errors.append(f"MT5: {msg}")

        mt5_tags = [t for t in tags if t["id"] == "mt5"]
        processed = bool(mt5_tags) and all(t["status"] == "success" for t in mt5_tags)
        return {"processed": processed, "action": action, "tags": tags, "errors": errors}

    return {"processed": False, "action": action, "tags": [], "errors": []}
