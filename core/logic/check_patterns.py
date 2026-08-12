"""Tekshiruvchi lichka javobini tanish — shablon dvigateli (TZ v2 6.4, B-3).

Tirik odamning erkin matni bilan ishlaydi, shuning uchun qat'iy qoidalar:

1. **Tartib** (6.4.3): CHECK_FAILED → CHECK_ERROR → CHECK_PASSED. Salbiy
   javob ijobiy so'zni o'z ichiga olishi mumkin ("bazada BOR emas") —
   salbiy shablonlar birinchi tekshiriladi.
2. **Ikkala-mos → noaniq**: matn ham PASSED, ham FAILED shabloniga mos
   kelsa, natija AMBIGUOUS — tizim HECH QACHON taxmin qilmaydi.
3. **Butun so'z standart**: "bor" sh abloni "borligi" ichida topilmaydi.

Shablon formatlari (6.4.4):
    o'tdi          — butun so'z (standart)
    ~bazada bor    — substring (ichida qidiriladi)
    =✅            — aynan tenglik (normallashtirishdan keyin)
    re:o'?t(di|gan)— regex (tajribali foydalanuvchi uchun)

Saqlash: `settings` jadvalida JSON ro'yxat (har kategoriya alohida kalit) —
adminbot orqali jonli tahrirlanadi, kodda hech narsa qotib qolmaydi.
"""

import enum
import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from core.logic.settings_store import get_setting, set_setting

log = logging.getLogger("check_patterns")


class CheckCategory(str, enum.Enum):
    CHECK_FAILED = "CHECK_FAILED"  # ovoz o'tmagan / topilmadi
    CHECK_ERROR = "CHECK_ERROR"  # xato / "qayta yuboring" / noto'g'ri nomer
    CHECK_PASSED = "CHECK_PASSED"  # ovoz o'tgan / bazada bor


# 6.4.3 — tekshirish tartibi: salbiy avval, ijobiy oxirida.
_MATCH_ORDER = (
    CheckCategory.CHECK_FAILED,
    CheckCategory.CHECK_ERROR,
    CheckCategory.CHECK_PASSED,
)

_SETTING_KEYS = {
    CheckCategory.CHECK_FAILED: "CHECK_PATTERNS_FAILED",
    CheckCategory.CHECK_ERROR: "CHECK_PATTERNS_ERROR",
    CheckCategory.CHECK_PASSED: "CHECK_PATTERNS_PASSED",
}

# 6.4.2 — apostrof variantlari birxillashtiriladi.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "`": "'", "ʼ": "'"})
_WS_RE = re.compile(r"\s+")


class AmbiguousMatch(Exception):
    """Matn ham salbiy, ham ijobiy shablonga mos keldi (6.4.3) —
    chaqiruvchi NEEDS_ADMIN'ga o'tkazishi kerak."""

    def __init__(self, categories: list[CheckCategory]) -> None:
        self.categories = categories
        super().__init__(f"Ikkala kategoriyaga mos: {[c.value for c in categories]}")


def normalize(text: str) -> str:
    """6.4.2 — taqqoslashdan oldin matnni tozalash."""
    return _WS_RE.sub(" ", text.translate(_APOSTROPHES).lower()).strip()


def _match_spans(pattern: str, normalized_text: str) -> list[tuple[int, int]]:
    """Shablonning matndagi barcha mosliklari (boshlanish, tugash) oralig'i.

    Bo'sh ro'yxat = mos emas. `pattern` ham normallashtirilgan holda
    solishtiriladi (adminbot saqlashda normallashtiradi, himoya uchun bu
    yerda ham).
    """
    if pattern.startswith("re:"):
        try:
            return [m.span() for m in re.finditer(pattern[3:], normalized_text)]
        except re.error:
            log.warning("Noto'g'ri regex shablon e'tiborsiz qoldirildi: %r", pattern)
            return []
    if pattern.startswith("="):
        if normalized_text == normalize(pattern[1:]):
            return [(0, len(normalized_text))]
        return []
    if pattern.startswith("~"):
        needle = normalize(pattern[1:])
        if not needle:
            return []
        return [
            m.span() for m in re.finditer(re.escape(needle), normalized_text)
        ]
    # Standart: butun so'z (6.4.3) — "bor" "borligi" ichida topilmasin.
    return [
        m.span()
        for m in re.finditer(
            rf"(?<!\w){re.escape(normalize(pattern))}(?!\w)", normalized_text
        )
    ]


def pattern_matches(pattern: str, normalized_text: str) -> bool:
    return bool(_match_spans(pattern, normalized_text))


def _category_spans(
    patterns: dict[CheckCategory, list[str]], category: CheckCategory, text: str
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for p in patterns.get(category, []):
        spans.extend(_match_spans(p, text))
    return spans


def _covered(inner: tuple[int, int], outers: list[tuple[int, int]]) -> bool:
    return any(o[0] <= inner[0] and inner[1] <= o[1] for o in outers)


def classify(text: str, patterns: dict[CheckCategory, list[str]]) -> CheckCategory | None:
    """Javob matnini kategoriyaga ajratadi.

    Qaytaradi: mos kategoriya, yoki None (hech biriga mos emas — kutish/
    tanilmagan).

    PASSED va FAILED birga mos kelganda ikki qoida kesishadi (6.4.3):
    - Salbiy ibora ijobiy so'zni O'Z ICHIGA olsa ("bazada BOR emas" —
      "bor" mosligi "~bor emas" mosligining ichida) — bu haqiqiy salbiy
      javob, natija FAILED (tartib qoidasi).
    - Ijobiy moslik salbiydan ALOHIDA joyda tursa ("o'tdi yoki o'tmadi") —
      haqiqiy qarama-qarshilik, `AmbiguousMatch` (tizim taxmin qilmaydi).
    """
    normalized = normalize(text)
    if not normalized:
        return None

    failed_spans = _category_spans(patterns, CheckCategory.CHECK_FAILED, normalized)
    error_spans = _category_spans(patterns, CheckCategory.CHECK_ERROR, normalized)
    passed_spans = _category_spans(patterns, CheckCategory.CHECK_PASSED, normalized)

    if failed_spans:
        standalone_passed = [s for s in passed_spans if not _covered(s, failed_spans)]
        if standalone_passed:
            raise AmbiguousMatch(
                [CheckCategory.CHECK_FAILED, CheckCategory.CHECK_PASSED]
            )
        return CheckCategory.CHECK_FAILED

    if error_spans:
        return CheckCategory.CHECK_ERROR

    if passed_spans:
        return CheckCategory.CHECK_PASSED

    return None


# --------------------------------------------------------------------------- #
# Saqlash (settings jadvalida JSON ro'yxat)
# --------------------------------------------------------------------------- #


async def get_patterns(session: AsyncSession, category: CheckCategory) -> list[str]:
    raw = await get_setting(session, _SETTING_KEYS[category], "[]")
    try:
        value = json.loads(raw)
        return [str(p) for p in value] if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


async def get_all_patterns(session: AsyncSession) -> dict[CheckCategory, list[str]]:
    return {cat: await get_patterns(session, cat) for cat in CheckCategory}


async def add_pattern(session: AsyncSession, category: CheckCategory, pattern: str) -> None:
    """Shablon qo'shadi (formatlar 6.4.4; oddiy matn normallashtiriladi)."""
    if not pattern.startswith(("re:", "=", "~")):
        pattern = normalize(pattern)
    if not pattern:
        raise ValueError("Bo'sh shablon qo'shib bo'lmaydi.")
    patterns = await get_patterns(session, category)
    if pattern in patterns:
        return  # idempotent
    patterns.append(pattern)
    await set_setting(session, _SETTING_KEYS[category], json.dumps(patterns))


async def remove_pattern(
    session: AsyncSession, category: CheckCategory, index: int
) -> str | None:
    """Indeks bo'yicha o'chiradi (1 dan boshlab — adminbot ro'yxati bilan mos).
    O'chirilgan shablonni qaytaradi, indeks noto'g'ri bo'lsa None."""
    patterns = await get_patterns(session, category)
    if not 1 <= index <= len(patterns):
        return None
    removed = patterns.pop(index - 1)
    await set_setting(session, _SETTING_KEYS[category], json.dumps(patterns))
    return removed


async def missing_categories(session: AsyncSession) -> list[CheckCategory]:
    """6.4.7 — har kategoriyada kamida bitta shablon bo'lmaguncha tekshiruv
    dvigateli ishga tushmaydi (v1 `missing_patterns` naqshi)."""
    result = []
    for category in CheckCategory:
        if not await get_patterns(session, category):
            result.append(category)
    return result
