"""Skrinshot FAYL sifatida yuborilsa ham ushlanishi kerak.

Jonli holat: admin ovozni oldi, skrinshotni mijozga tashladi — lekin
guruhga tushmadi va logda hech qanday iz qolmadi (na "Partiya qayd
etildi", na "nomer topilmadi" ogohlantirishi).

Sabab: chiquvchi kuzatuv faqat `event.photo` ni tekshirardi. Telegram
rasmni ikki xil yuboradi — "rasm sifatida" (siqilgan, `photo`) va "fayl
sifatida" (siqilmagan, `document` + `image/*`). Ikkinchisi butunlay
e'tiborsiz qolardi.

Skrinshotni fayl qilib yuborish odatiy hol: siqilmagan rasmda matn
aniqroq ko'rinadi.
"""

import pytest

from teleton_service.manual_relay import _is_screenshot


class _Hujjat:
    def __init__(self, mime):
        self.mime_type = mime


class _Event:
    def __init__(self, photo=None, document=None):
        self.photo = photo
        self.document = document


def test_compressed_photo_is_caught():
    """Eski yo'l — avvalgidek ishlashi kerak."""
    assert _is_screenshot(_Event(photo=object())) is True


@pytest.mark.parametrize(
    "mime",
    ["image/png", "image/jpeg", "image/webp", "IMAGE/PNG"],
)
def test_image_sent_as_file_is_caught(mime):
    """Asosiy tuzatish: fayl sifatida yuborilgan rasm."""
    assert _is_screenshot(_Event(document=_Hujjat(mime))) is True


@pytest.mark.parametrize(
    "mime",
    ["application/pdf", "application/zip", "video/mp4", "audio/ogg", "text/plain"],
)
def test_non_image_files_are_ignored(mime):
    """Admin mijozga PDF yoki arxiv yuborsa — bu skrinshot emas, guruhga
    forward qilinmasligi kerak."""
    assert _is_screenshot(_Event(document=_Hujjat(mime))) is False


def test_plain_text_is_ignored():
    assert _is_screenshot(_Event()) is False


def test_document_without_mime_is_ignored():
    """Mime yo'q bo'lsa taxmin qilmaymiz — noma'lum fayl guruhga
    tushmagani yaxshiroq."""
    assert _is_screenshot(_Event(document=_Hujjat(None))) is False
