"""Umumiy kalit-qiymat tizim sozlamalari — TZ 9.1 (bildirishnoma batafsil rejimi)."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Setting

NOTIFY_VERBOSE_KEY = "NOTIFY_VERBOSE"


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    row = await session.get(Setting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def is_verbose(session: AsyncSession) -> bool:
    return await get_setting(session, NOTIFY_VERBOSE_KEY, "0") == "1"


async def set_verbose(session: AsyncSession, value: bool) -> None:
    await set_setting(session, NOTIFY_VERBOSE_KEY, "1" if value else "0")
