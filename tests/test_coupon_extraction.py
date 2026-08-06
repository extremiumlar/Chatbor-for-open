"""Audit J-2 — kupon matn ichidan aniqlanishi, aynan-6-raqam talabi emas
(TZ 1-bo'lim: mijoz tabiiy suhbat ichida yozadi, xuddi nomer kabi)."""

from core.logic.coupon import extract_coupon


def test_extracts_bare_six_digits():
    assert extract_coupon("123456") == "123456"


def test_extracts_from_surrounding_text():
    assert extract_coupon("kuponim 123456 mana") == "123456"
    assert extract_coupon("mana kod: 654321.") == "654321"


def test_extracts_with_internal_spacing_variant():
    # "123 456" ichida uzluksiz 6 ta raqam yo'q — bu ataylab tanilmaydi
    # (aniq, bir butun kod talab qilinadi); lekin "123456" o'zi har doim topiladi.
    assert extract_coupon("123 456") is None


def test_does_not_match_digits_inside_longer_number():
    # 9/12 xonali telefon nomeri ichidan tasodifiy 6 ta raqam kupon
    # deb noto'g'ri qabul qilinmasligi kerak.
    assert extract_coupon("998901234567") is None
    assert extract_coupon("901234567") is None


def test_returns_none_for_plain_text():
    assert extract_coupon("salom, qalaysiz?") is None


def test_first_isolated_six_digit_run_wins():
    assert extract_coupon("avval 111222 keyin 333444") == "111222"
