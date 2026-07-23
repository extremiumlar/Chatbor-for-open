from core.logic.phone import extract_phone, format_for_bot


def test_extracts_plain_national_number():
    assert extract_phone("mening raqamim 997894561 shu") == "998997894561"


def test_extracts_international_with_plus():
    assert extract_phone("+998997894561") == "998997894561"


def test_extracts_with_spaces():
    assert extract_phone("+998 99 789 45 61") == "998997894561"


def test_extracts_with_dashes():
    assert extract_phone("99-789-45-61 ga aloqaga chiqing") == "998997894561"


def test_rejects_invalid_operator_code():
    # "12" haqiqiy O'zbekiston operator kodi emas
    assert extract_phone("123456789") is None


def test_rejects_wrong_length():
    assert extract_phone("12345") is None
    assert extract_phone("1234567890123") is None


def test_rejects_six_digit_coupon_as_phone():
    assert extract_phone("111111") is None


def test_ignores_surrounding_conversation_text():
    text = "Salom! Narxi 500000 so'm. Nomerim: 90 123 45 67, kutaman."
    assert extract_phone(text) == "998901234567"


def test_format_for_bot_variants():
    canonical = "998901234567"
    assert format_for_bot(canonical, "+998XXXXXXXXX") == "+998901234567"
    assert format_for_bot(canonical, "998XXXXXXXXX") == "998901234567"
    assert format_for_bot(canonical, "XXXXXXXXX") == "901234567"
