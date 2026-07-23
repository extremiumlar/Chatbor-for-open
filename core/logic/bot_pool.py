"""Tekshiruv botlari pool (navbat) tizimi — TZ 3-bo'lim.

Har bot bir vaqtda faqat bitta case yuritadi (3-bo'lim boshi). Bo'sh bot
tanlashda LRU (eng uzoq ishlatilmagani) qoidasi qo'llaniladi (3.1). Hamma bot
band bo'lsa, case ichki navbatga tushadi va bot bo'shagach avtomatik
tayinlanadi (Q45).
"""

import asyncio
import datetime
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Bot

OnAssigned = Callable[[int, int], Awaitable[None]]


async def ensure_bots_seeded(session: AsyncSession, usernames: list[str]) -> None:
    """Test/mock muhitda pool'ni berilgan username'lar bilan to'ldiradi (idempotent)."""
    result = await session.execute(select(Bot.username))
    existing = {row[0] for row in result.all()}
    for username in usernames:
        if username not in existing:
            session.add(Bot(username=username))
    await session.commit()


async def list_bots(session: AsyncSession) -> list[Bot]:
    """Adminbot `/bots` uchun — barcha tekshiruv botlari holati (TZ 3.3, 9.2)."""
    result = await session.execute(select(Bot).order_by(Bot.id))
    return list(result.scalars().all())


async def add_bot(
    session: AsyncSession,
    username: str,
    phone_format: str = "+998XXXXXXXXX",
    owner_admin_id: int | None = None,
    needs_start_greeting: bool = False,
) -> Bot | None:
    """Adminbot `/addbot` uchun — yangi tekshiruv bot qo'shadi (TZ 3.3, 9.5).

    Username allaqachon mavjud bo'lsa None qaytaradi (chaqiruvchi xabar beradi).
    `owner_admin_id` — MVP-5 (Q55): berilmasa (None) bot umumiy (bitta akkaunt)
    pool'ga tegishli bo'ladi, aks holda faqat shu admin'ning Teleton sessiyasi
    undan foydalana oladi (har admin+bot mustaqil slot).
    """
    result = await session.execute(select(Bot).where(Bot.username == username))
    if result.scalars().first() is not None:
        return None
    bot = Bot(
        username=username,
        phone_format=phone_format,
        owner_admin_id=owner_admin_id,
        needs_start_greeting=needs_start_greeting,
    )
    session.add(bot)
    await session.commit()
    await session.refresh(bot)
    return bot


class BotPoolManager:
    def __init__(self, on_assigned: OnAssigned | None = None, owner_admin_id: int | None = None) -> None:
        # Bo'sh bot topilmaganda navbatga tushgan case_id'lar (FIFO).
        self._queue: list[int] = []
        self._lock = asyncio.Lock()
        self.on_assigned = on_assigned
        # MVP-5 (Q55) — None bo'lsa umumiy (owner_admin_id IS NULL) botlar
        # pool'i, aks holda faqat shu admin'ga tegishli botlar orasidan tanlaydi.
        self.owner_admin_id = owner_admin_id

    async def acquire(self, session: AsyncSession, case_id: int) -> Bot | None:
        """Bo'sh botni case'ga biriktiradi. Bo'sh bot yo'q bo'lsa navbatga qo'yib None qaytaradi."""
        async with self._lock:
            bot = await self._select_free_bot(session)
            if bot is None:
                self._queue.append(case_id)
                return None
            await self._assign(session, bot, case_id)
            return bot

    async def release(self, session: AsyncSession, bot_id: int) -> None:
        """Botni bo'shatadi. Navbatda case bo'lsa, darhol shu (yoki boshqa bo'sh) botga tayinlaydi."""
        async with self._lock:
            bot = await session.get(Bot, bot_id)
            if bot is None:
                return
            bot.is_busy = False
            bot.current_case_id = None
            bot.last_used_at = datetime.datetime.utcnow()
            bot.total_processed += 1
            await session.commit()

            if not self._queue:
                return

            next_case_id = self._queue.pop(0)
            next_bot = await self._select_free_bot(session)
            if next_bot is None:
                # Amalda sodir bo'lmasligi kerak (hozirgina bot bo'shadi),
                # lekin xavfsizlik uchun case'ni navbat boshiga qaytaramiz.
                self._queue.insert(0, next_case_id)
                return

            await self._assign(session, next_bot, next_case_id)
            if self.on_assigned is not None:
                await self.on_assigned(next_case_id, next_bot.id)

    async def force_release(self, session: AsyncSession, bot_id: int) -> None:
        """TIMEOUT holatida botni majburan bo'shatish (12-bo'lim) — release bilan bir xil."""
        await self.release(session, bot_id)

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    async def _select_free_bot(self, session: AsyncSession) -> Bot | None:
        stmt = (
            select(Bot)
            .where(
                Bot.is_active.is_(True),
                Bot.is_busy.is_(False),
                Bot.owner_admin_id == self.owner_admin_id,
            )
            .order_by(Bot.last_used_at.asc().nulls_first())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def _assign(self, session: AsyncSession, bot: Bot, case_id: int) -> None:
        bot.is_busy = True
        bot.current_case_id = case_id
        await session.commit()
