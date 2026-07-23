"""Mijozga yuboriladigan shablonlar — TZ 7.2, 9.2 (`/templates`).

Adminbot va Teleton alohida jarayon bo'lgani uchun (TZ 13.1) shablonlar
xotirada keshlanmaydi — har chaqiriqda bazadan o'qiladi, shunda bir jarayonda
qilingan o'zgarish ikkinchisiga darhol ko'rinadi.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import texts
from core.models import Template

# TZ 7.2 dagi 7 ta shablon turi. Boshlang'ich qiymatlar core/texts.py'dan.
DEFAULTS: dict[str, str] = {
    "COUPON_REQUEST": texts.COUPON_REQUEST,
    "CONFIRMED": texts.CONFIRMED,
    "REJECTED": texts.REJECTED,
    "EXPIRED_RETRY": texts.EXPIRED_RETRY,
    "IMAGE_INSTEAD_OF_TEXT": texts.IMAGE_INSTEAD_OF_TEXT,
    "DUPLICATE_ACTIVE": texts.DUPLICATE_ACTIVE,
    "ALREADY_CONFIRMED": texts.ALREADY_CONFIRMED,
    "DUPLICATE_COUPON": texts.DUPLICATE_COUPON,
}


async def ensure_templates_seeded(session: AsyncSession) -> None:
    result = await session.execute(select(Template.key))
    existing = {row[0] for row in result.all()}
    for key, value in DEFAULTS.items():
        if key not in existing:
            session.add(Template(key=key, value=value))
    await session.commit()


async def get_template(session: AsyncSession, key: str) -> str:
    row = await session.get(Template, key)
    if row is not None:
        return row.value
    return DEFAULTS[key]


async def set_template(session: AsyncSession, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"Noma'lum shablon kaliti: {key}")
    row = await session.get(Template, key)
    if row is None:
        session.add(Template(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def list_templates(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Template))
    stored = {row.key: row.value for row in result.scalars().all()}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}
