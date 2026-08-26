"""Tekshiruvchi BOT menyusi bo'ylab navigatsiya.

Jonli o'rganish (2026-08-25, @ovoztekshiruvchi_bot) shuni ko'rsatdi:

  * nomerni shunchaki yuborib bo'lmaydi — avval menyudan o'tish kerak:
    "📁 Loyihalar" -> loyiha tugmasi -> "🔍 Tekshirish" -> nomer;
  * loyiha tugmasi bosilganda bot YANGI xabar yubormaydi, mavjudini
    TAHRIRLAYDI — yangi xabar kutilsa, navigatsiya osilib qolardi;
  * javob bergach bot tekshirish rejimidan CHIQADI ("ℹ️ Tushunmadim"),
    shuning uchun sikl HAR NOMER uchun to'liq takrorlanadi.

Bu testlar shu uch xususiyatni qotirib qo'yadi.
"""

import asyncio

import pytest

from teleton_service.checker_bot import (
    CheckerBotError,
    CheckerBotNavigator,
    _buttons,
    _find_button,
)


class _Tugma:
    def __init__(self, text, data):
        self.text = text
        self.data = data


class _Qator:
    def __init__(self, buttons):
        self.buttons = buttons


class _Markup:
    def __init__(self, rows):
        self.rows = rows


class _Xabar:
    def __init__(self, id, text="", tugmalar=None, out=False):
        self.id = id
        self.raw_text = text
        self.out = out
        self.reply_markup = (
            _Markup([_Qator([_Tugma(t, d) for t, d in tugmalar])]) if tugmalar else None
        )


# Jonli botdan olingan HAQIQIY tugmalar. callback_data ATAYLAB "p1" formatida
# EMAS (2026-08-25 jonli xato: bu formatni taxmin qilib, oxiri xato chiqqan
# edi) — moslash endi TUGMA MATNI ("#1") bo'yicha, callback_data qanday
# bo'lishidan qat'i nazar ishlashi kerak.
_RO_YXAT = [
    ("📋 #1 · 9088 ovoz", b"cb_a1b2"),
    ("➕ Loyiha qo'shish", b"project:add"),
    ("🗑 Loyiha o'chirish", b"project:del"),
]
_KARTOCHKA = [
    ("📩 Excel", b"cb_x1"),
    ("🔍 Tekshirish", b"cb_check_9"),
    ("⬅️ Loyihalarimga", b"menu:projects"),
]


class _SoxtaKlient:
    """Botning haqiqiy xatti-harakatini taqlid qiladi."""

    def __init__(self, tahrirlaydi=True):
        self.xabarlar = [_Xabar(1, "eski", out=False)]
        self.yuborilgan: list[str] = []
        self.bosilgan: list[bytes] = []
        self.tahrirlaydi = tahrirlaydi
        self._keyingi_id = 2

    def _qo_sh(self, text, tugmalar=None, out=False):
        m = _Xabar(self._keyingi_id, text, tugmalar, out=out)
        self._keyingi_id += 1
        self.xabarlar.append(m)
        return m

    async def send_message(self, peer, text):
        self.yuborilgan.append(text)
        m = self._qo_sh(text, out=True)
        if text == "📁 Loyihalar":
            self._qo_sh("📁 Loyihalarim (1 ta)", _RO_YXAT)
        return m

    async def get_messages(self, peer, limit=1, ids=None):
        if ids is not None:
            return next((m for m in self.xabarlar if m.id == ids), None)
        return list(reversed(self.xabarlar))[:limit]

    async def __call__(self, request):
        data = request.data
        self.bosilgan.append(data)
        if data == b"cb_a1b2":
            hedef = next(m for m in self.xabarlar if m.id == request.msg_id)
            if self.tahrirlaydi:
                # HAQIQIY xatti-harakat: xabar tahrirlanadi.
                hedef.raw_text = "📋 Loyiha ma'lumotlari"
                hedef.reply_markup = _Markup(
                    [_Qator([_Tugma(t, d) for t, d in _KARTOCHKA])]
                )
            else:
                self._qo_sh("📋 Loyiha ma'lumotlari", _KARTOCHKA)
        elif data == b"cb_check_9":
            self._qo_sh("🔍 Ovoz tekshirish\n\nTelefon raqamni kiriting.")
        return object()


@pytest.fixture(autouse=True)
def tez(monkeypatch):
    """Kutishlarni tezlashtiradi — testlar soniyalarni kutmasin."""
    import teleton_service.checker_bot as cb

    monkeypatch.setattr(cb, "_TEKSHIR_ORALIQ", 0.001)
    monkeypatch.setattr(cb, "_QADAM_KUTISH", 0.3)
    haqiqiy = asyncio.sleep

    async def tez_sleep(sekund):
        await haqiqiy(0)

    monkeypatch.setattr(cb.asyncio, "sleep", tez_sleep)


# --------------------------------------------------------------------------- #
# Tugma qidirish
# --------------------------------------------------------------------------- #


def test_buttons_are_extracted():
    m = _Xabar(1, "x", _KARTOCHKA)
    assert [t for t, _ in _buttons(m)] == ["📩 Excel", "🔍 Tekshirish", "⬅️ Loyihalarimga"]


def test_message_without_keyboard():
    assert _buttons(_Xabar(1, "x")) == []


def test_find_button_by_text():
    """Qidiruv TUGMA MATNI bo'yicha — callback_data qanday bo'lishidan
    qat'iy nazar (2026-08-25 jonli xato shu farqni ochdi)."""
    m = _Xabar(1, "x", _KARTOCHKA)
    assert _find_button(m, "Tekshir") == b"cb_check_9"
    assert _find_button(m, "yo'q-bunday-matn") is None


def test_find_button_ignores_callback_data_format():
    """Loyiha tugmasi "#1" matni bilan topiladi, callback_data "p1" bo'lishi
    SHART emas."""
    m = _Xabar(1, "x", _RO_YXAT)
    assert _find_button(m, "#1") == b"cb_a1b2"


# --------------------------------------------------------------------------- #
# To'liq sikl
# --------------------------------------------------------------------------- #


async def test_full_navigation_sends_the_number():
    klient = _SoxtaKlient()
    nav = CheckerBotNavigator(klient, "bot", "1")

    natija = await nav.send_number("998901234567")

    assert natija is not None
    # Tartib muhim: avval menyu, keyin nomer.
    assert klient.yuborilgan == ["📁 Loyihalar", "998901234567"]
    assert klient.bosilgan == [b"cb_a1b2", b"cb_check_9"]


async def test_works_when_bot_edits_instead_of_replying():
    """Loyiha tugmasi bosilganda bot xabarni TAHRIRLAYDI — yangi xabar
    kutilsa navigatsiya osilib qolardi."""
    klient = _SoxtaKlient(tahrirlaydi=True)
    nav = CheckerBotNavigator(klient, "bot", "1")

    assert await nav.send_number("998901234567") is not None


async def test_every_number_repeats_the_whole_cycle():
    """Bot javob bergach tekshirish rejimidan chiqadi — keyingi nomer
    uchun menyudan qaytadan o'tish SHART."""
    klient = _SoxtaKlient()
    nav = CheckerBotNavigator(klient, "bot", "1")

    await nav.send_number("998901111111")
    await nav.send_number("998902222222")

    assert klient.yuborilgan.count("📁 Loyihalar") == 2
    assert klient.bosilgan.count(b"cb_check_9") == 2


async def test_requests_are_serialised():
    """Bot HOLATLI: ikki sikl aralashsa, ikkinchisi birinchisining
    "nomer kutish" holatini o'g'irlab, javoblar chalkashib ketardi."""
    klient = _SoxtaKlient()
    nav = CheckerBotNavigator(klient, "bot", "1")

    await asyncio.gather(
        nav.send_number("998901111111"), nav.send_number("998902222222")
    )

    # Har sikl to'liq: 2 ta "Loyihalar" + 2 ta nomer, aralashmagan.
    menyu = [i for i, t in enumerate(klient.yuborilgan) if t == "📁 Loyihalar"]
    assert len(menyu) == 2
    assert klient.yuborilgan[menyu[0] + 1] != "📁 Loyihalar"


# --------------------------------------------------------------------------- #
# Xatolar — so'rov yo'qolmasligi kerak
# --------------------------------------------------------------------------- #


async def test_missing_project_button_raises():
    """Bot menyusi o'zgarsa — jimgina noto'g'ri tugma bosilmasin."""
    klient = _SoxtaKlient()

    async def bo_sh_royxat(peer, text):
        klient.yuborilgan.append(text)
        klient._qo_sh("📁 Loyihalarim", [("➕ Loyiha qo'shish", b"project:add")])
        return _Xabar(99, text, out=True)

    klient.send_message = bo_sh_royxat
    nav = CheckerBotNavigator(klient, "bot", "1")

    with pytest.raises(CheckerBotError, match="loyihasi tugmasi topilmadi"):
        await nav.send_number("998901234567")


async def test_silent_bot_raises():
    """Bot javob bermasa — cheksiz kutib qolmasin."""
    klient = _SoxtaKlient()

    async def jim(peer, text):
        klient.yuborilgan.append(text)
        return _Xabar(99, text, out=True)

    klient.send_message = jim
    nav = CheckerBotNavigator(klient, "bot", "1")

    with pytest.raises(CheckerBotError, match="javob bermadi"):
        await nav.send_number("998901234567")
