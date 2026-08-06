"""Matn ichidan 6 xonali kupon kodini aniqlash — TZ 2-bo'lim (5-qadam).

Audit J-2 — avval kupon faqat butun xabar AYNAN 6 ta raqamdan iborat
bo'lsagina tanilardi (`^\\d{6}$`), nomer aniqlashdan (`extract_phone`, TZ
4.1) farqli — u matn ICHIDAN qidiradi ("gap orasida tashlaydi", TZ 1-bo'lim).
Bu nomuvofiqlik: mijoz "kuponim 123456" yoki bo'shliq bilan "123 456" deb
yozsa, xabar butunlay e'tiborsiz qoldirilardi.
"""

import re

# 6 ta ketma-ket raqam, ikkala tomondan ham boshqa raqam bilan
# "uzilmagan" bo'lishi kerak — aks holda 9-12 xonali telefon nomeri
# ichidan tasodifiy 6 ta raqam kupon deb noto'g'ri qabul qilinardi.
_COUPON_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")


def extract_coupon(text: str) -> str | None:
    """Matn ichidan 6 xonali kuponni topadi. Topilmasa `None`."""
    match = _COUPON_RE.search(text)
    return match.group() if match else None
