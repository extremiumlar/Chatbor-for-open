"""Tekshiruv botni TANISH shablonlari — TZ 7.1, 9.4 (Q16).

Bular mijozga yuboriladigan `core.logic.templates` shablonlaridan BUTUNLAY
BOSHQA narsa (TZ 7-bo'lim, Q47 — ikki xil to'plam alohida): bular tekshiruv
bot (qora quti)ning O'Z chiqishini tanib olish uchun, mijozga hech qachon
yuborilmaydi.

TZ 9.4 (Q16): bu 4 ta shablon **majburiy** — real bot rejimi ular
to'liq kiritilmaguncha ishga tushmaydi (`all_patterns_configured`).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import BotPattern

REQUIRED_KEYS = ("COUPON_REQUEST", "CONFIRMED", "EXPIRED", "REJECTED")


class UnrecognizedBotResponseError(Exception):
    """Real tekshiruv bot javob berdi, lekin matni hech qaysi ma'lum
    shablonga mos kelmadi — TZ 8-bo'lim: "Bot javobi tanilmagan/noaniq
    format" holati `NEEDS_ADMIN`ga o'tadi, TIMEOUT/qayta-urinish EMAS
    (bot javob berdi, muammo tushunarsizlikda, ulanishda emas)."""


async def get_pattern(session: AsyncSession, key: str) -> str | None:
    row = await session.get(BotPattern, key)
    return row.value if row is not None else None


async def set_pattern(session: AsyncSession, key: str, value: str) -> None:
    if key not in REQUIRED_KEYS:
        raise ValueError(f"Noma'lum bot-tanish kaliti: {key}")
    row = await session.get(BotPattern, key)
    if row is None:
        session.add(BotPattern(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def list_patterns(session: AsyncSession) -> dict[str, str | None]:
    result = await session.execute(select(BotPattern))
    stored = {row.key: row.value for row in result.scalars().all()}
    return {key: stored.get(key) for key in REQUIRED_KEYS}


async def missing_patterns(session: AsyncSession) -> list[str]:
    patterns = await list_patterns(session)
    return [key for key, value in patterns.items() if not value]


async def all_patterns_configured(session: AsyncSession) -> bool:
    return not await missing_patterns(session)


def recognize(message: str, pattern: str) -> bool:
    """Sodda mos kelish qoidasi — kichik/katta harf farqisiz substring
    tekshiruvi. Real bot javobida o'zgaruvchi qism (kupon raqami, vaqt)
    bo'lishi mumkin, shuning uchun aniq tenglik emas, substring kifoya
    (TZ 3.2 — bot pool'da har bot bir vaqtda bitta case yuritgani uchun
    qaysi case ekanini bilish shart emas, faqat NATIJA turini bilish kerak).
    """
    return pattern.strip().lower() in message.strip().lower()
