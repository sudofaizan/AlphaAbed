"""Interpret SL values from channel messages (price vs points)."""


def sl_message_is_points(sl: float | None, entry: float, unit: str) -> bool:
    if sl is None:
        return False
    u = (unit or "auto").lower()
    if u == "points":
        return True
    if u == "price":
        return False
    return sl < entry * 0.85
