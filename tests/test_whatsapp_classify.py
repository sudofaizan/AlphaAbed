from signals.whatsapp_classify import classify_whatsapp_text, is_whatsapp_open_signal


SAMPLE = """GOLD BUY 4155

TP 4161
TP 4168
TP 4174
TP 4180

SL 4147"""


def test_whatsapp_open_signal():
    assert is_whatsapp_open_signal(SAMPLE)
    p = classify_whatsapp_text(SAMPLE)
    assert p.kind == "open_signal"
    assert p.signal
    assert p.signal.side == "buy"
    assert p.signal.sl == 4147.0
    assert p.signal.tp == 4161.0
    assert p.signal.tp_levels == [4161.0, 4168.0, 4174.0, 4180.0]


def test_whatsapp_rejects_hit_tp():
    p = classify_whatsapp_text("#GOLD BUY (4155) HIT TP 1 😎")
    assert p.kind != "open_signal"
