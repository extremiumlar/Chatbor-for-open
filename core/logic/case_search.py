"""Murojaatlar qidiruv/filtr — TZ 11.6 (Web panel, MVP-6).

Faqat o'qish uchun — panel hech qanday holat o'zgartirmaydi.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import CaseStatus
from core.models import Case


async def search_cases(
    session: AsyncSession,
    phone: str | None = None,
    status: CaseStatus | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 200,
) -> list[Case]:
    stmt = select(Case).order_by(Case.id.desc()).limit(limit)

    if phone:
        stmt = stmt.where(Case.phone.contains(phone))
    if status is not None:
        stmt = stmt.where(Case.status == status)
    if date_from is not None:
        stmt = stmt.where(
            Case.created_at >= datetime.datetime.combine(date_from, datetime.time.min)
        )
    if date_to is not None:
        stmt = stmt.where(Case.created_at <= datetime.datetime.combine(date_to, datetime.time.max))

    result = await session.execute(stmt)
    return list(result.scalars().all())
