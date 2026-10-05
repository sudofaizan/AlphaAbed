"""Classify Abeid FX channel messages and parse trade signals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MessageKind = Literal[
    "open_signal",
    "close_all",
    "partial_close",
    "sl_fragment",
    "incomplete_signal",
    "promo",
    "commentary",
    "unknown",
]


@dataclass
class TradeSignal:
    side: Literal["buy", "sell"]
    symbol: str
    entry: float | None = None
    entry_min: float | None = None
    entry_max: float | None = None
    sl: float | None = None
    tp: float | None = None
    market: bool = False


@dataclass
class ParsedMessage:
    kind: MessageKind
    signal: TradeSignal | None = None
    reason: str = ""
    raw_text: str = ""


_RE_SL = re.compile(r"\bSL\s+(\d+(?:\.\d+)?)", re.I)
_RE_TP = re.compile(r"\bTP\s+(\d+(?:\.\d+)?)", re.I)
_RE_SIDE = re.compile(r"\b(BUY|SELL)\b", re.I)
_RE_LOOSE_SIDE = re.compile(r"\b(BUY|SELL)\s", re.I)
_RE_XAU = re.compile(r"\b(XAUUSD|GOLD)\b", re.I)
_RE_AT = re.compile(r"\b(?:NOW\s+)?AT\s+(\d+(?:\.\d+)?)", re.I)
_RE_FROM_RANGE = re.compile(
    r"\bFROM\s+(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)", re.I
)
_RE_GOLD_AT = re.compile(r"\b(?:LETS?|LET'S)\s+BUY\s+GOLD\s+AT\s+(\d+(?:\.\d+)?)", re.I)
_RE_BUY_GOLD = re.compile(r"\bBUY\s+GOLD\s+AT\s+(\d+(?:\.\d+)?)", re.I)

_PROMO_MARKERS = (
    "justmarkets",
    "ib code",
    "lifetime vip",
    "join vip",
    "join for free",
    "dm @",
    "@abeidfx01",
    "account management",
    "profit split",
    "minimum deposit",
    "minimum balance",
    "mt5 login",
    "tiktok",
    "youtube",
    "youtu.be",
    "whatsapp",
    "mentorship",
    "open a justmarkets",
    "partner-change",
)

_CLOSE = re.compile(r"^\s*(?:closing\s+all|close\s+all|closed)\.?\s*$", re.I)
_PARTIAL = re.compile(r"collect\s+partials", re.I)
_ONLY_SL = re.compile(r"^\s*SL\s+\d+(?:\.\d+)?\s*$", re.I)


def _normalize(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"!+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _promo_score(text: str) -> int:
    lower = text.lower()
    score = sum(1 for m in _PROMO_MARKERS if m in lower)
    if "http://" in lower or "https://" in lower:
        score += 2
    if "🚨" in text and ("vip" in lower or "dm" in lower):
        score += 1
    return score


def _parse_levels(text: str) -> tuple[float | None, float | None]:
    sl_m = _RE_SL.search(text)
    tp_m = _RE_TP.search(text)
    sl = float(sl_m.group(1)) if sl_m else None
    tp = float(tp_m.group(1)) if tp_m else None
    return sl, tp


def _parse_side_and_symbol(text: str) -> tuple[str | None, str | None]:
    raw = (text or "").strip()
    side_m = _RE_SIDE.search(raw) or _RE_LOOSE_SIDE.search(raw + " ")
    if not side_m and _RE_GOLD_AT.search(raw):
        return "buy", "XAUUSD"
    if not side_m:
        return None, None
    side = side_m.group(1).lower()
    sym = "XAUUSD" if _RE_XAU.search(raw) else None
    if sym is None and (_RE_GOLD_AT.search(raw) or re.search(r"\bGOLD\b", raw, re.I)):
        sym = "XAUUSD"
    if sym is None and side_m:
        sym = "XAUUSD"
    return side, sym


def _parse_entry(text: str) -> tuple[float | None, float | None, float | None, bool]:
    rng = _RE_FROM_RANGE.search(text)
    if rng:
        return None, float(rng.group(1)), float(rng.group(2)), False
    for pat in (_RE_GOLD_AT, _RE_BUY_GOLD, _RE_AT):
        m = pat.search(text)
        if m:
            return float(m.group(1)), None, None, False
    if _RE_SIDE.search(text) and re.search(r"\bNOW\b", text, re.I):
        return None, None, None, True
    return None, None, None, False


def parse_trade_signal(text: str) -> TradeSignal | None:
    text = _normalize(text)
    side, symbol = _parse_side_and_symbol(text)
    sl, tp = _parse_levels(text)
    if side and not symbol and sl is not None:
        symbol = "XAUUSD"
    if not side:
        return None
    if not symbol:
        return None
    entry, entry_min, entry_max, market = _parse_entry(text)
    if entry is None and entry_min is None and not market:
        if sl is not None:
            market = True
        else:
            return None
    return TradeSignal(
        side=side,
        symbol=symbol,
        entry=entry,
        entry_min=entry_min,
        entry_max=entry_max,
        sl=sl,
        tp=tp,
        market=market,
    )


def merge_sl_fragment(pending: TradeSignal, sl_text: str) -> TradeSignal | None:
    if pending.sl is not None:
        return None
    sl, _ = _parse_levels(sl_text)
    if sl is None:
        return None
    pending.sl = sl
    return pending


def classify_text(text: str) -> ParsedMessage:
    text = _normalize(text)
    if not text:
        return ParsedMessage(kind="unknown", reason="empty", raw_text=text)

    if _CLOSE.match(text):
        return ParsedMessage(kind="close_all", reason="close instruction", raw_text=text)

    if _PARTIAL.search(text):
        return ParsedMessage(
            kind="partial_close", reason="partial close instruction", raw_text=text
        )

    if _ONLY_SL.match(text):
        sl, _ = _parse_levels(text)
        sig = TradeSignal(side="buy", symbol="XAUUSD", sl=sl)
        return ParsedMessage(
            kind="sl_fragment",
            signal=sig,
            reason="standalone SL line (may follow prior entry)",
            raw_text=text,
        )

    if _promo_score(text) >= 2:
        return ParsedMessage(kind="promo", reason="marketing / VIP content", raw_text=text)

    signal = parse_trade_signal(text)
    if signal:
        if signal.sl is None and not signal.market and signal.entry is None and signal.entry_min is None:
            return ParsedMessage(
                kind="incomplete_signal",
                signal=signal,
                reason="side/symbol without SL or entry",
                raw_text=text,
            )
        if signal.sl is None:
            return ParsedMessage(
                kind="incomplete_signal",
                signal=signal,
                reason="missing SL (can use default SL points if configured)",
                raw_text=text,
            )
        return ParsedMessage(
            kind="open_signal", signal=signal, reason="actionable trade", raw_text=text
        )

    if _RE_SIDE.search(text) and _RE_XAU.search(text):
        return ParsedMessage(
            kind="incomplete_signal",
            reason="mentions trade but could not parse",
            raw_text=text,
        )

    if len(text) < 120 and _promo_score(text) == 0 and not _RE_SIDE.search(text):
        return ParsedMessage(kind="commentary", reason="status / chat", raw_text=text)

    if _promo_score(text) >= 1:
        return ParsedMessage(kind="promo", reason="likely promo", raw_text=text)

    return ParsedMessage(kind="unknown", reason="unclassified", raw_text=text)


def format_signal_line(parsed: ParsedMessage, message_id: int | None = None) -> str:
    prefix = f"id={message_id} " if message_id is not None else ""
    if parsed.kind == "open_signal" and parsed.signal:
        s = parsed.signal
        entry = s.entry
        if s.entry_min is not None and s.entry_max is not None:
            entry_str = f"{s.entry_min}-{s.entry_max}"
        elif s.market and entry is None:
            entry_str = "MARKET"
        elif entry is not None:
            entry_str = str(entry)
        else:
            entry_str = "?"
        tp = s.tp if s.tp is not None else "-"
        return (
            f"{prefix}[OPEN] {s.side.upper()} {s.symbol} @ {entry_str} "
            f"SL {s.sl} TP {tp}"
        )
    return f"{prefix}[{parsed.kind.upper()}] {parsed.reason}"
