"""Real tekshiruv botga Telethon orqali ulanuvchi adapter — TZ 3.2, 7.1.

⚠️ MUHIM: bu klass ATAYLAB hech qanday HAQIQIY tekshiruv botiga qarshi
sinalmagan. Foydalanuvchi MVP-5 boshlanishida real bot ma'lumotlarini
(username + namuna xabarlar) hali bermagani va jonli ulanishga alohida
ruxsat so'ralmagani uchun (AI_AGENT_PROMPT.md: "Real tekshiruv botlariga
ULANMA... Real bot integratsiyasi MVP-5 da, alohida ruxsat bilan").

Kod TZ 3.2 va 7.1-bo'limlardagi tavsifga asoslanib yozilgan (Telethon'ning
standart `client.conversation()` so'rov-javob mexanizmi orqali), lekin
ishlab chiqarishga o'tishdan oldin kamida bitta haqiqiy bot bilan qo'lda
tekshirilishi SHART — buni faqat siz (real bot username va ruxsat bilan)
qila olasiz.

Ishlash tamoyili (TZ 3.2): har bot bir vaqtda faqat bitta case yuritadi,
shuning uchun botdan kelgan keyingi xabar aniq shu so'rovning javobi —
maxsus reply/marker shart emas. `client.conversation()` aynan shu
so'rov-javob juftligini ifodalaydi.
"""

import logging

from core.db import get_session
from core.enums import CaseStatus
from core.logic.bot_patterns import UnrecognizedBotResponseError, get_pattern, list_patterns, recognize
from core.models import Bot

log = logging.getLogger("real_bot_adapter")

# Telethon conversation'ning bitta so'rovga javob kutish muddati — bu
# case_manager'ning umumiy retry/backoff qatlamidan ALOHIDA (ichki, bitta
# urinish ichidagi kutish).
_RESPONSE_TIMEOUT_SECONDS = 30


class RealVerificationBotAdapter:
    """`core.logic.case_manager.VerificationBot` protokolini amalga oshiradi."""

    def __init__(self, client, session_factory=None) -> None:
        self._client = client
        # DI qilinishi mumkin (testlarda izolyatsiyalangan baza bilan
        # `_classify`ni haqiqiy Telethon tarmog'isiz sinash uchun); ishlab
        # chiqarishda standart `core.db.get_session` ishlatiladi.
        self._session_factory = session_factory or get_session
        self._greeted_bot_ids: set[int] = set()

    async def request_coupon(self, bot: Bot, phone: str) -> str:
        async with self._client.conversation(bot.username, timeout=_RESPONSE_TIMEOUT_SECONDS) as conv:
            if bot.needs_start_greeting and bot.id not in self._greeted_bot_ids:
                # TZ Q54 — ba'zi botlar avval /start talab qilishi mumkin.
                await conv.send_message("/start")
                await conv.get_response()
                self._greeted_bot_ids.add(bot.id)

            await conv.send_message(phone)
            response = await conv.get_response()
            text = response.raw_text or ""

        # Audit J-10 — avval bu javob HECH QANDAY tekshiruvsiz qabul
        # qilinardi (faqat check_coupon o'z javobini shablonga solishtirardi).
        # Agar real bot nomerga kutilmagan narsa bilan javob bersa (xatolik,
        # yoki "allaqachon tasdiqlangan" kabi o'z-o'zidan yakunlovchi javob),
        # tizim buni sezmay baribir mijozdan kupon so'rardi — bot tomonidagi
        # haqiqiy anomaliyani yashirardi.
        if not await self._matches(text, "COUPON_REQUEST"):
            raise UnrecognizedBotResponseError(text)
        return text

    async def check_coupon(self, bot: Bot, coupon: str) -> tuple[CaseStatus, str]:
        async with self._client.conversation(bot.username, timeout=_RESPONSE_TIMEOUT_SECONDS) as conv:
            await conv.send_message(coupon)
            response = await conv.get_response()
            text = response.raw_text or ""

        status = await self._classify(text)
        if status is None:
            raise UnrecognizedBotResponseError(text)
        return status, text

    async def _matches(self, text: str, key: str) -> bool:
        async with self._session_factory() as session:
            pattern = await get_pattern(session, key)
        return bool(pattern) and recognize(text, pattern)

    async def _classify(self, text: str) -> CaseStatus | None:
        async with self._session_factory() as session:
            patterns = await list_patterns(session)

        for key, status in (
            ("CONFIRMED", CaseStatus.CONFIRMED),
            ("EXPIRED", CaseStatus.EXPIRED),
            ("REJECTED", CaseStatus.REJECTED),
        ):
            pattern = patterns.get(key)
            if pattern and recognize(text, pattern):
                return status
        return None
