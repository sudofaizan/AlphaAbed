"""Pause Telegram / WhatsApp / background checks (e.g. weekend)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config_store import load_config, save_config
from app.datetime_util import format_card_time_ist


def _parse_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def automation_paused(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    if not cfg.get("automation_paused"):
        return False
    resume_at = _parse_utc(cfg.get("automation_resume_at"))
    if resume_at and datetime.now(timezone.utc) >= resume_at:
        return False
    return True


def maybe_auto_unpause() -> dict[str, Any]:
    """Clear pause when resume time passed; returns updated config."""
    cfg = load_config()
    if not cfg.get("automation_paused"):
        return cfg
    resume_at = _parse_utc(cfg.get("automation_resume_at"))
    now = datetime.now(timezone.utc)
    if resume_at and now >= resume_at:
        return save_config(
            {
                "automation_paused": False,
                "automation_resume_at": None,
            }
        )
    return cfg


def pause_automation(resume_at_iso: str) -> dict[str, Any]:
    resume = _parse_utc(resume_at_iso)
    if not resume:
        raise ValueError("Invalid resume date/time")
    if resume <= datetime.now(timezone.utc):
        raise ValueError("Resume time must be in the future")
    return save_config(
        {
            "automation_paused": True,
            "automation_resume_at": resume.isoformat(),
        }
    )


def resume_automation_now() -> dict[str, Any]:
    return save_config(
        {
            "automation_paused": False,
            "automation_resume_at": None,
        }
    )


def pause_status(cfg: dict | None = None) -> dict[str, Any]:
    cfg = maybe_auto_unpause()
    paused = automation_paused(cfg)
    resume_raw = cfg.get("automation_resume_at")
    return {
        "automation_paused": paused,
        "automation_resume_at": resume_raw,
        "automation_resume_at_ist": format_card_time_ist(resume_raw),
    }
