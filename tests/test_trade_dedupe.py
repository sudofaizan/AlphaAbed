import tempfile
import os
from pathlib import Path

import app.trade_dedupe as td


def test_reserve_blocks_second_call(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("ALPHAABED_DATA_DIR", tmp)
        monkeypatch.setattr(td, "_path", Path(tmp) / "traded_signals.json")
        ok1, _ = td.reserve_trade_execution("telegram", 1568)
        ok2, reason = td.reserve_trade_execution("telegram", 1568)
        assert ok1 is True
        assert ok2 is False
        assert "already executed" in reason
        ok3, _ = td.reserve_trade_execution("telegram", 1569)
        assert ok3 is True


def test_cooldown_blocks_then_allows(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("ALPHAABED_DATA_DIR", tmp)
        monkeypatch.setattr(td, "_path", Path(tmp) / "traded_signals.json")
        assert td.check_trade_cooldown(300)[0] is True
        td.mark_trade_executed()
        ok, reason = td.check_trade_cooldown(300)
        assert ok is False
        assert "cooldown" in reason
