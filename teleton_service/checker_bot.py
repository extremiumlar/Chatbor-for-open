"""Tekshiruvchi BOT bilan ishlash — inline menyu bo'ylab avtomatik yurish.

Avval tekshiruvchi ODAM edi: nomer uning lichkasiga oddiy matn bo'lib
ketardi, javobini ham odam yozardi. `@ovoztekshiruvchi_bot` esa menyuli
bot — nomerni qabul qilishidan oldin uni kerakli holatga OLIB BORISH kerak.

Jonli o'rganish natijasi (2026-08-25), har nomer uchun to'liq sikl:

    1. "📁 Loyihalar" matni yuboriladi
         -> "📁 Loyihalarim (N ta)" ro'yxati,
            tugma: '📋 #1 · 9088 ovoz'   data=project:view:p1
    2. loyiha tugmasi bosiladi (bot XABARNI TAHRIRLAYDI, yangisini yubormaydi)
         -> "📋 Loyiha ma'lumotlari",
            tugma: '🔍 Tekshirish'       data=project_action:check:p1
    3. "Tekshirish" bosiladi
         -> YANGI xabar: "🔍 Ovoz tekshirish ... raqamni kiriting"
    4. nomer matn bo'lib yuboriladi
         -> '✅ Topildi! (1 ta natija) ...'   yoki   '❌ Topilmadi.'

MUHIM: bot javob bergach tekshirish rejimidan CHIQADI. Keyingi nomerni
shunchaki yuborib bo'lmaydi — "ℹ️ Tushunmadim" javobini beradi. Shuning
uchun sikl HAR NOMER uchun to'liq takrorlanadi.

Shuningdek: bot BITTA akkaunt bilan ishlaydi (obuna o'sha akkauntga
bog'langan), shuning uchun barcha so'rovlar bitta "relay" adminining
akkauntidan ketadi — case qaysi adminniki bo'lishidan qat'i nazar.
"""

import asyncio
import logging

from telethon.tl import functions

log = logging.getLogger("checker_bot")

# Bot javob berguncha kutish (navigatsiya qadamlari uchun).
_QADAM_KUTISH = 20.0
_TEKSHIR_ORALIQ = 1.0


class CheckerBotError(Exception):
    """Navigatsiya kutilganidek ketmadi — so'rov navbatda qoladi."""


def _buttons(message):
    """Xabardagi barcha inline tugmalar: (matn, callback_data)."""
    markup = getattr(message, "reply_markup", None)
    if markup is None:
        return []
    chiqdi = []
    for row in getattr(markup, "rows", []):
        for tugma in row.buttons:
            data = getattr(tugma, "data", None)
            if data is not None:
                chiqdi.append((getattr(tugma, "text", ""), data))
    return chiqdi


def _find_button(message, needle: bytes):
    """`callback_data` ichida `needle` bo'lgan birinchi tugma."""
    for _, data in _buttons(message):
        if needle in data:
            return data
    return None


class CheckerBotNavigator:
    """Bitta admin klienti orqali tekshiruvchi bot menyusini boshqaradi.

    Bir vaqtda faqat BITTA sikl ishlaydi (`_lock`): bot holatli — ikki
    so'rov aralashsa, ikkinchisi birinchisining "nomer kutish" holatini
    o'g'irlab, javoblar chalkashib ketardi.
    """

    def __init__(self, client, bot_username: str, project_slug: str = "p1"):
        self.client = client
        self.bot_username = bot_username
        self.project_slug = project_slug
        self._lock = asyncio.Lock()

    async def _kutib_ol(self, keyin_id: int, kutish: float = _QADAM_KUTISH):
        """Berilgan id'dan KEYIN kelgan birinchi BOT xabarini qaytaradi."""
        o_tdi = 0.0
        while o_tdi < kutish:
            await asyncio.sleep(_TEKSHIR_ORALIQ)
            o_tdi += _TEKSHIR_ORALIQ
            for m in await self.client.get_messages(self.bot_username, limit=5):
                if m.id > keyin_id and not m.out:
                    return m
        return None

    async def _bos(self, message, data: bytes):
        """Inline tugmani bosadi."""
        await self.client(
            functions.messages.GetBotCallbackAnswerRequest(
                peer=self.bot_username, msg_id=message.id, data=data
            )
        )

    async def _oxirgi_id(self) -> int:
        xabarlar = await self.client.get_messages(self.bot_username, limit=1)
        return xabarlar[0].id if xabarlar else 0

    async def send_number(self, phone: str) -> int | None:
        """Menyudan o'tib, nomerni tekshiruvga yuboradi.

        Qaytaradi: yuborilgan nomer xabarining id'si (javobni bog'lash
        uchun), yoki xato bo'lsa `CheckerBotError` ko'taradi.

        Javobning O'ZI bu yerda o'qilmaydi — u odatdagi kiruvchi xabar
        sifatida `manual_relay.on_incoming` ga tushadi va u yerdan
        `check_engine.handle_checker_reply` ga boradi. Ya'ni tanish
        shablonlari va natija oqimi o'zgarishsiz qoladi.
        """
        async with self._lock:
            # 1-qadam — loyihalar ro'yxati.
            oldin = await self._oxirgi_id()
            await self.client.send_message(self.bot_username, "📁 Loyihalar")
            ro_yxat = await self._kutib_ol(oldin)
            if ro_yxat is None:
                raise CheckerBotError("bot 'Loyihalar' ga javob bermadi")

            # 2-qadam — loyihani ochish. Bot javob o'rniga SHU xabarni
            # tahrirlaydi, shuning uchun yangi xabar kutilmaydi.
            loyiha = _find_button(ro_yxat, f"project:view:{self.project_slug}".encode())
            if loyiha is None:
                raise CheckerBotError(
                    f"'{self.project_slug}' loyihasi tugmasi topilmadi: "
                    f"{[t for t, _ in _buttons(ro_yxat)]}"
                )
            await self._bos(ro_yxat, loyiha)
            await asyncio.sleep(2.0)
            kartochka = await self.client.get_messages(
                self.bot_username, ids=ro_yxat.id
            )
            if kartochka is None:
                raise CheckerBotError("loyiha kartochkasi o'qilmadi")

            # 3-qadam — "Tekshirish".
            tekshir = _find_button(
                kartochka, f"project_action:check:{self.project_slug}".encode()
            )
            if tekshir is None:
                raise CheckerBotError(
                    f"'Tekshirish' tugmasi topilmadi: "
                    f"{[t for t, _ in _buttons(kartochka)]}"
                )
            oldin = await self._oxirgi_id()
            await self._bos(kartochka, tekshir)
            so_rov = await self._kutib_ol(oldin)
            if so_rov is None:
                raise CheckerBotError("bot nomer so'rovini ko'rsatmadi")

            # 4-qadam — nomer.
            xabar = await self.client.send_message(self.bot_username, phone)
            log.info(
                "Tekshiruvchi botga nomer yuborildi: %s (xabar #%s).",
                phone,
                xabar.id,
            )
            return xabar.id
