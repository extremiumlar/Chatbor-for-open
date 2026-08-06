"""Mijozlar ro'yxati/tarixi — CRM ko'rinishi (TZ 11.6, Web panel MVP-6).

Faqat o'qish uchun — panel hech qanday holat o'zgartirmaydi.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Case, User


async def list_customers(
    session: AsyncSession,
    search: str | None = None,
    limit: int = 200,
    viewer_admin_id: int | None = None,
    can_see_all: bool = True,
) -> list[User]:
    stmt = select(User).order_by(User.last_seen.desc()).limit(limit)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (User.phone.contains(search))
            | (User.tg_username.ilike(like))
            | (User.display_name.ilike(like))
        )
    if not can_see_all:
        # Audit K-4 (TZ 11.0, Q51) — oddiy admin faqat o'ziga biriktirilgan
        # yoki hali hech kimga biriktirilmagan mijozlarni ko'radi.
        stmt = stmt.where(
            (User.assigned_admin_id.is_(None)) | (User.assigned_admin_id == viewer_admin_id)
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def case_count_for_user(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(select(func.count()).select_from(Case).where(Case.user_id == user_id))
    return result.scalar_one()


async def cases_for_user(session: AsyncSession, user_id: int) -> list[Case]:
    result = await session.execute(
        select(Case).where(Case.user_id == user_id).order_by(Case.id.desc())
    )
    return list(result.scalars().all())
