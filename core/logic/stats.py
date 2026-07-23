"""Statistika — TZ 10-bo'lim.

Har admin/lichka bo'yicha alohida taqsimot (TZ 10-bo'lim, 2-3-band) hozircha
qo'shilmagan: `Case.assigned_admin_id` MVP-5'gacha (ko'p Teleton akkaunti)
haqiqiy ma'noga ega bo'lmaydi — bitta akkaunt bilan bu taqsimot mazmunsiz
bo'lar edi. Shu bois faqat umumiy (barcha tizim bo'yicha) sonlar hisoblanadi.
"""

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import CaseStatus
from core.models import Case

PROBLEM_STATUSES = (CaseStatus.DUPLICATE_ACTIVE, CaseStatus.NEEDS_ADMIN, CaseStatus.SUSPICIOUS_HOLD)


@dataclass
class Stats:
    today_count: int
    by_status: dict[str, int]
    problem_count: int


async def gather_stats(session: AsyncSession) -> Stats:
    # SQLite CURRENT_TIMESTAMP (created_at ustuni) doim UTC — mahalliy sana
    # bilan solishtirsak, UTC+5 kabi zonalarda kuning bir necha soatida
    # "bugungi" hisob noto'g'ri chiqadi. Shuning uchun UTC sanadan foydalanamiz.
    today_start = datetime.datetime.combine(datetime.datetime.utcnow().date(), datetime.time.min)
    today_count = (
        await session.execute(
            select(func.count()).select_from(Case).where(Case.created_at >= today_start)
        )
    ).scalar_one()

    status_rows = (
        await session.execute(select(Case.status, func.count()).group_by(Case.status))
    ).all()
    by_status = {status.value: count for status, count in status_rows}

    problem_count = (
        await session.execute(
            select(func.count()).select_from(Case).where(Case.status.in_(PROBLEM_STATUSES))
        )
    ).scalar_one()

    return Stats(today_count=today_count, by_status=by_status, problem_count=problem_count)
