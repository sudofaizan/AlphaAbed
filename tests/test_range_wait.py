from signals.classify import classify_text, parse_trade_signal
from app.range_wait import distance_to_range_points, price_in_range, telegram_range_wait_needed


def test_from_range_not_market_without_now():
    t = "BUY XAUUSD FROM 3940-3935\n\nSL 3925"
    p = classify_text(t)
    assert p.kind == "open_signal"
    assert p.signal
    assert p.signal.market is False
    assert p.signal.entry_min == 3935.0
    assert p.signal.entry_max == 3940.0


def test_now_still_market():
    t = "SELL XAUUSD NOW AT 4147\n\nSL 4155"
    p = parse_trade_signal(t)
    assert p and p.market is True


def test_range_wait_needed():
    t = "BUY XAUUSD FROM 3940-3935\n\nSL 3925"
    parsed = classify_text(t)
    cfg = {"range_wait_enabled": True}
    assert telegram_range_wait_needed("telegram", parsed.signal, t, cfg)
    assert not telegram_range_wait_needed("telegram", parsed.signal, t.replace("FROM", "FROM NOW"), cfg)


def test_price_in_range_buy():
    assert price_in_range("buy", 3930, 3936, 3935, 3940)
    assert not price_in_range("buy", 3930, 3934, 3935, 3940)


def test_distance_below_buy_zone():
    pts, where = distance_to_range_points("buy", 3875.0, 3875.5, 3935, 3940, 0.01)
    assert where == "below"
    assert pts > 2000
