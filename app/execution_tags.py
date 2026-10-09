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


def _mt5_leg_tags(legs: dict[str, Any], *, mt5_on: bool) -> tuple[list[dict[str, Any]], list[str]]:
    tags: list[dict[str, Any]] = []
    errors: list[str] = []
    if not mt5_on:
        return tags, errors
    mt5_legs = [(k, v) for k, v in legs.items() if k.startswith("mt5:")]
    if not mt5_legs and legs.get("mt5"):
        mt5_legs = [("mt5", legs["mt5"])]
    if not mt5_legs:
        tags.append(_tag("mt5", "MT5", "failed", "no response"))
        errors.append("MT5: no response")
        return tags, errors
    for key, leg in mt5_legs:
        label = leg.get("label") or key.replace("mt5:", "MT5 ")
        tag_id = key if key.startswith("mt5:") else "mt5"
        if leg.get("ok") and _mt5_result_ok(leg.get("result")):
            tags.append(_tag(tag_id, label, "success"))
        elif leg:
            msg = leg.get("error") or _mt5_error_text(leg.get("result"))
            tags.append(_tag(tag_id, label, "failed", msg))
            errors.append(f"{label}: {msg}")
        else:
            tags.append(_tag(tag_id, label, "failed", "no response"))
            errors.append(f"{label}: no response")
    return tags, errors


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

        mt5_tags, mt5_errs = _mt5_leg_tags(legs, mt5_on=mt5_on)
        tags.extend(mt5_tags)
        errors.extend(mt5_errs)

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
        if action == "close_all":
            bundle = trade.get("result") or {}
            legs = bundle.get("legs") or {}
            mt5_tags, mt5_errs = _mt5_leg_tags(legs, mt5_on=mt5_on)
            tags.extend(mt5_tags)
            errors.extend(mt5_errs)
        else:
            bundle = trade.get("result") or {}
            legs = bundle.get("legs") or {}
            if isinstance(legs, dict) and any(k.startswith("mt5:") for k in legs):
                mt5_tags, mt5_errs = _mt5_leg_tags(legs, mt5_on=mt5_on)
                tags.extend(mt5_tags)
                errors.extend(mt5_errs)
            else:
                res = trade.get("result")
                if mt5_on:
                    if _mt5_result_ok(res):
                        tags.insert(0, _tag("mt5", "MT5", "success"))
                    else:
                        msg = _mt5_error_text(res)
                        tags.insert(0, _tag("mt5", "MT5", "failed", msg))
                        errors.append(f"MT5: {msg}")

        mt5_tags_only = [t for t in tags if t["id"].startswith("mt5")]
        processed = bool(mt5_tags_only) and all(t["status"] == "success" for t in mt5_tags_only)
        return {"processed": processed, "action": action, "tags": tags, "errors": errors}

    return {"processed": False, "action": action, "tags": [], "errors": []}
