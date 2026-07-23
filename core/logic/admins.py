"""Admin ro'yxati va kirish nazorati — TZ 12.2 (faqat `admins` jadvalidagi
Telegram ID-lar Adminbotga buyruq bera oladi)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Admin


async def ensure_admins_seeded(session: AsyncSession, tg_ids: list[int]) -> None:
    """.env dagi ADMIN_TG_IDS bilan boshlang'ich admin ro'yxatini to'ldiradi (idempotent)."""
    result = await session.execute(select(Admin.tg_user_id))
    existing = {row[0] for row in result.all()}
    for tg_id in tg_ids:
        if tg_id not in existing:
            session.add(Admin(tg_user_id=tg_id, name=str(tg_id)))
    await session.commit()


async def is_admin(session: AsyncSession, tg_user_id: int) -> bool:
    result = await session.execute(select(Admin.id).where(Admin.tg_user_id == tg_user_id))
    return result.scalars().first() is not None


async def list_admin_tg_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(Admin.tg_user_id))
    return [row[0] for row in result.all()]
