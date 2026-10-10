"""Parse GOLD PIPS PRO–style WhatsApp channel signals (plain / markdown text)."""

from __future__ import annotations

import re
import unicodedata

from signals.classify import ParsedMessage, TradeSignal, format_signal_line

_RE_GOLD_SIDE = re.compile(
    r"\bGOLD\s+(BUY|SELL)\b(?:\s+(\d+(?:\.\d+)?))?",
    re.I,
)
_RE_TP_LINE = re.compile(r"^\s*TP\s+(\d+(?:\.\d+)?)\s*$", re.I | re.M)
_RE_SL_LINE = re.compile(r"^\s*SL\s+(\d+(?:\.\d+)?)\s*$", re.I | re.M)

_NOISE = re.compile(
    r"HIT\s+TP|RUNNING|\+\s*PIPS|PIPS\s+PROFIT|ALL\s+TP|exness|http://|https://|"
    r"TRADE WITH|TRUSTED BROKER|Partner Code|Ready\b",
    re.I,
)


def normalize_whatsapp_text(text: str) -> str:
    """Strip WhatsApp markdown / unicode bold; keep line breaks for TP/SL blocks."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("*", "").replace("_", "")
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def is_whatsapp_open_signal(text: str) -> bool:
    norm = normalize_whatsapp_text(text)
    if not norm or _NOISE.search(norm):
        return False
    if not _RE_SL_LINE.search(norm):
        return False
    if not _RE_GOLD_SIDE.search(norm):
        return False
    if not _RE_TP_LINE.search(norm):
        return False
    return True


def parse_whatsapp_signal(text: str) -> TradeSignal | None:
    norm = normalize_whatsapp_text(text)
    if not is_whatsapp_open_signal(norm):
        return None
    side_m = _RE_GOLD_SIDE.search(norm)
    if not side_m:
        return None
    side = side_m.group(1).lower()
    entry = float(side_m.group(2)) if side_m.group(2) else None
    sl_m = _RE_SL_LINE.search(norm)
    if not sl_m:
        return None
    sl = float(sl_m.group(1))
    tps = [float(x) for x in _RE_TP_LINE.findall(norm)]
    tp = tps[0] if tps else None
    return TradeSignal(
        side=side,
        symbol="XAUUSD",
        entry=entry,
        sl=sl,
        tp=tp,
        tp_levels=tps or None,
        market=True,
    )


def classify_whatsapp_text(text: str) -> ParsedMessage:
    norm = normalize_whatsapp_text(text)
    if not norm:
        return ParsedMessage(kind="unknown", reason="empty", raw_text=text or "")

    if _NOISE.search(norm):
        return ParsedMessage(kind="commentary", reason="whatsapp update / promo", raw_text=text)

    signal = parse_whatsapp_signal(text)
    if signal:
        tps = getattr(signal, "tp_levels", [])
        tp_note = f", {len(tps)} TP" if tps else ""
        return ParsedMessage(
            kind="open_signal",
            signal=signal,
            reason=f"WhatsApp GOLD {signal.side.upper()}{tp_note}",
            raw_text=text,
        )

    if re.search(r"\bGOLD\b", norm, re.I) and re.search(r"\b(BUY|SELL)\b", norm, re.I):
        return ParsedMessage(
            kind="incomplete_signal",
            reason="whatsapp GOLD mention without full SL/TP block",
            raw_text=text,
        )

    return ParsedMessage(kind="unknown", reason="unclassified whatsapp", raw_text=text)


def format_whatsapp_signal_line(parsed: ParsedMessage, message_id: str | None = None) -> str:
    prefix = f"wa={message_id} " if message_id else ""
    if parsed.kind == "open_signal" and parsed.signal:
        return prefix + format_signal_line(parsed, None).replace("[OPEN]", "[WA OPEN]")
    return prefix + f"[{parsed.kind.upper()}] {parsed.reason}"
