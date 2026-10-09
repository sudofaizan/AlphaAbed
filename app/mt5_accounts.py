"""Multiple MT5 (AlphaFX) accounts from config — parallel trading."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from signals.alphafx_client import AlphaFxClient, AlphaFxConfig


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _account_from_legacy(cfg: dict) -> dict[str, Any]:
    return {
        "id": "default",
        "label": "Primary",
        "enabled": True,
        "base_url": (cfg.get("mt5_base_url") or "").strip(),
        "api_key": (cfg.get("mt5_api_key") or "").strip(),
        "symbol": (cfg.get("mt5_symbol") or "XAUUSD.pr").strip(),
    }


def normalize_mt5_accounts(cfg: dict) -> dict:
    """Ensure mt5_accounts list exists; sync legacy mt5_* from first enabled account."""
    cfg = deepcopy(cfg)
    raw = cfg.get("mt5_accounts")
    accounts: list[dict[str, Any]]
    if isinstance(raw, list) and len(raw) > 0:
        accounts = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            acc = {
                "id": (row.get("id") or _new_id()).strip(),
                "label": (row.get("label") or f"Account {i + 1}").strip(),
                "enabled": bool(row.get("enabled", True)),
                "base_url": (row.get("base_url") or "").strip(),
                "api_key": (row.get("api_key") or "").strip(),
                "symbol": (row.get("symbol") or cfg.get("mt5_symbol") or "XAUUSD.pr").strip(),
            }
            if acc["base_url"] and acc["api_key"]:
                accounts.append(acc)
        if not accounts:
            accounts = [_account_from_legacy(cfg)]
    else:
        accounts = [_account_from_legacy(cfg)]

    cfg["mt5_accounts"] = accounts
    primary = next((a for a in accounts if a.get("enabled")), accounts[0])
    cfg["mt5_base_url"] = primary["base_url"]
    cfg["mt5_api_key"] = primary["api_key"]
    cfg["mt5_symbol"] = primary["symbol"]
    return cfg


def list_enabled_mt5_accounts(cfg: dict) -> list[dict[str, Any]]:
    cfg = normalize_mt5_accounts(cfg)
    return [a for a in cfg["mt5_accounts"] if a.get("enabled")]


def mt5_client_for_account(account: dict[str, Any]) -> AlphaFxClient:
    return AlphaFxClient(
        AlphaFxConfig(
            base_url=account["base_url"],
            api_key=account["api_key"],
            symbol=account["symbol"],
        )
    )


def primary_mt5_client(cfg: dict) -> AlphaFxClient:
    enabled = list_enabled_mt5_accounts(cfg)
    if not enabled:
        return mt5_client_for_account(normalize_mt5_accounts(cfg)["mt5_accounts"][0])
    return mt5_client_for_account(enabled[0])


def leg_key_for_account(account_id: str) -> str:
    return f"mt5:{account_id}"
