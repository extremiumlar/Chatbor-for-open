"""TZ v2 B-3 — shablon dvigateli (6.4) testlari."""

import pytest

from core.logic.check_patterns import (
    AmbiguousMatch,
    CheckCategory,
    add_pattern,
    classify,
    get_all_patterns,
    get_patterns,
    missing_categories,
    normalize,
    pattern_matches,
    remove_pattern,
)

PASSED = CheckCategory.CHECK_PASSED
FAILED = CheckCategory.CHECK_FAILED
ERROR = CheckCategory.CHECK_ERROR


def _patterns(passed=(), failed=(), error=()):
    return {PASSED: list(passed), FAILED: list(failed), ERROR: list(error)}


# --------------------------------------------------------------------------- #
# normalize
# --------------------------------------------------------------------------- #


def test_normalize_case_whitespace_apostrophes():
    assert normalize("  O'TDI   ekan ") == "o'tdi ekan"
    assert normalize("oʻtdi") == "o'tdi"
    assert normalize("o`tdi") == "o'tdi"


# --------------------------------------------------------------------------- #
# pattern_matches — formatlar (6.4.4)
# --------------------------------------------------------------------------- #


def test_whole_word_default():
    assert pattern_matches("bor", "bazada bor ekan")
    assert not pattern_matches("bor", "borligi aniqlanmadi")  # so'z ichida emas


def test_substring_format():
    assert pattern_matches("~bazada bor", "bu nomer bazada bor ekan")


def test_exact_format():
    assert pattern_matches("=✅", "✅")
    assert not pattern_matches("=✅", "✅ o'tdi")


def test_regex_format():
    assert pattern_matches("re:o'?t(di|gan)", "otdi")
    assert pattern_matches("re:o'?t(di|gan)", "o'tgan")


def test_invalid_regex_ignored():
    assert not pattern_matches("re:[", "har qanday matn")


# --------------------------------------------------------------------------- #
# classify — tartib va noaniqlik (6.4.3)
# --------------------------------------------------------------------------- #


def test_negative_phrase_containing_positive_word_is_failed():
    """"bazada bor emas" — "bor" mosligi "~bor emas" ICHIDA — natija FAILED
    (salbiy ibora ijobiy so'zni qamrab olgan, bu haqiqiy salbiy javob)."""
    patterns = _patterns(passed=["bor"], failed=["~bor emas"])
    assert classify("bu nomer bazada bor emas", patterns) == FAILED


def test_conflicting_match_raises_ambiguous():
    """"o'tdi yoki o'tmadi" — mosliklar ALOHIDA joylarda — haqiqiy
    qarama-qarshilik, tizim taxmin qilmaydi."""
    patterns = _patterns(passed=["o'tdi"], failed=["o'tmadi"])
    with pytest.raises(AmbiguousMatch):
        classify("o'tdi yoki o'tmadi bilmadim", patterns)


def test_error_beats_passed_in_order():
    patterns = _patterns(passed=["bor"], error=["~qayta yuboring"])
    assert classify("xato, qayta yuboring. bor degani emas", patterns) == ERROR


def test_no_match_returns_none():
    patterns = _patterns(passed=["bor"], failed=["yo'q"])
    assert classify("bir daqiqa kutib turing", patterns) is None


def test_empty_text_returns_none():
    assert classify("   ", _patterns(passed=["bor"])) is None


def test_simple_passed():
    patterns = _patterns(passed=["bor", "o'tdi", "=✅"], failed=["yo'q", "o'tmadi"])
    assert classify("O'TDI", patterns) == PASSED
    assert classify("✅", patterns) == PASSED
    assert classify("yo'q bunday nomer", patterns) == FAILED


# --------------------------------------------------------------------------- #
# Saqlash (settings JSON)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_add_get_remove_patterns(session_factory):
    async with session_factory() as session:
        await add_pattern(session, PASSED, "  O'TDI  ")  # normallashadi
        await add_pattern(session, PASSED, "o'tdi")  # dublikat — qo'shilmaydi
        await add_pattern(session, PASSED, "~bazada bor")
        assert await get_patterns(session, PASSED) == ["o'tdi", "~bazada bor"]

        removed = await remove_pattern(session, PASSED, 1)
        assert removed == "o'tdi"
        assert await get_patterns(session, PASSED) == ["~bazada bor"]
        assert await remove_pattern(session, PASSED, 99) is None


@pytest.mark.asyncio
async def test_add_empty_pattern_rejected(session_factory):
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await add_pattern(session, PASSED, "   ")


@pytest.mark.asyncio
async def test_missing_categories_gate(session_factory):
    """6.4.7 — uch kategoriya to'lmaguncha dvigatel ishga tushmaydi."""
    async with session_factory() as session:
        assert len(await missing_categories(session)) == 3
        await add_pattern(session, PASSED, "bor")
        await add_pattern(session, FAILED, "yo'q")
        assert await missing_categories(session) == [ERROR]
        await add_pattern(session, ERROR, "xato")
        assert await missing_categories(session) == []

        all_patterns = await get_all_patterns(session)
        assert all_patterns[PASSED] == ["bor"]
