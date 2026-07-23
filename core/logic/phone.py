"""O'zbekiston telefon nomerini erkin matndan aniqlash — TZ 4-bo'lim, 4.1 (Q46).

Tasodifiy raqamlar (narx, sana) nomer deb noto'g'ri qabul qilinmasligi uchun
uzunlik + haqiqiy operator kodi ikkalasi ham tekshiriladi.
"""

import re

from core.config import settings

# Matn ichidan "telefonga o'xshagan" raqam ketma-ketligini topish uchun:
# ixtiyoriy +, keyin raqam/probel/chiziqcha/qavslardan iborat, kamida 9 ta raqam.
_CANDIDATE_RE = re.compile(r"\+?[\d][\d\s\-()]{7,16}\d")
_NON_DIGIT_RE = re.compile(r"[^\d]")


def _normalize_candidate(raw: str) -> str | None:
    """Probel/chiziqcha/qavslarni olib tashlab, faqat raqamlarni qoldiradi."""
    digits = _NON_DIGIT_RE.sub("", raw)

    if digits.startswith("998") and len(digits) == 12:
        national = digits[3:]
    elif len(digits) == 9:
        national = digits
    else:
        return None

    operator_code = national[:2]
    if operator_code not in settings.uz_operator_codes:
        return None

    return "998" + national


def extract_phone(text: str) -> str | None:
    """Matn ichidan haqiqiy O'zbekiston nomerini topib, kanonik shaklda qaytaradi.

    Kanonik shakl: "998XXXXXXXXX" (12 raqam, "+"siz). Topilmasa None.
    """
    for match in _CANDIDATE_RE.finditer(text):
        normalized = _normalize_candidate(match.group())
        if normalized is not None:
            return normalized
    return None


def format_for_bot(canonical_phone: str, phone_format: str) -> str:
    """Kanonik "998XXXXXXXXX" nomerni bot kutgan formatga o'giradi (TZ 9.5)."""
    national = canonical_phone[3:]
    if phone_format == "+998XXXXXXXXX":
        return "+998" + national
    if phone_format == "998XXXXXXXXX":
        return "998" + national
    if phone_format == "XXXXXXXXX":
        return national
    raise ValueError(f"Noma'lum phone_format: {phone_format}")
