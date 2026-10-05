import unittest

from signals.classify import classify_text, parse_trade_signal


class TestClassify(unittest.TestCase):
    def test_open_sell_full(self):
        t = "SELL XAUUSD NOW AT 4147\n\nSL 4155"
        p = classify_text(t)
        self.assertEqual(p.kind, "open_signal")
        assert p.signal
        self.assertEqual(p.signal.side, "sell")
        self.assertEqual(p.signal.entry, 4147.0)
        self.assertEqual(p.signal.sl, 4155.0)

    def test_open_with_tp(self):
        t = "RECOVERY!\n\nSELL XAUUSD NOW AT 4160\n\nSL 4165\n\nTP 4110"
        p = classify_text(t)
        self.assertEqual(p.kind, "open_signal")
        assert p.signal
        self.assertEqual(p.signal.tp, 4110.0)

    def test_range_entry(self):
        t = "SELL XAUUSD FROM 4186-4193\n\nSL 4200\n\nTP 4148"
        p = classify_text(t)
        self.assertEqual(p.kind, "open_signal")
        assert p.signal
        self.assertEqual(p.signal.entry_min, 4186.0)
        self.assertEqual(p.signal.entry_max, 4193.0)

    def test_buy_gold(self):
        t = "LETS BUY GOLD AT 4142"
        s = parse_trade_signal(t)
        assert s
        self.assertEqual(s.side, "buy")
        p = classify_text(t)
        self.assertEqual(p.kind, "incomplete_signal")

    def test_close_all(self):
        self.assertEqual(classify_text("Closing all.").kind, "close_all")

    def test_promo(self):
        t = "Join my VIP\nIB CODE: eqzbw05f6k\nDM @AbeidFX01"
        self.assertEqual(classify_text(t).kind, "promo")

    def test_commentary(self):
        self.assertEqual(classify_text("Nice trade.").kind, "commentary")

    def test_sl_fragment(self):
        self.assertEqual(classify_text("SL 4134").kind, "sl_fragment")


if __name__ == "__main__":
    unittest.main()
