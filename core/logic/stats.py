"""Statistika — TZ 10-bo'lim.

Bu — v1 davridan qolgan umumiy ekran (`/stats`). Admin kesimidagi batafsil
ko'rsatkichlar `core/logic/v2_stats.py` da (`/vstats`).

TZ v2 §8.4 ko'rish cheklovi shu yerda ham amal qiladi: oddiy admin faqat
o'ziga biriktirilgan (yoki hali hech kimga biriktirilmagan) mijozlarning
case'larini ko'radi. Avval bu ekran hammaga hamma narsani ko'rsatardi —
jonli sinovda ADMIN rolidagi akkaunt boshqa adminning case'larini ham
sanoqda ko'rdi.
"""

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import PROBLEM_STATUSES, CaseStatus
from core.logic.case_admin import visible_to
from core.models import Case, User


@dataclass
class Stats:
    today_count: int
    by_status: dict[str, int]
    problem_count: int


async def gather_stats(
    session: AsyncSession,
    viewer_admin_id: int | None = None,
    can_see_all: bool = True,
) -> Stats:
    """TZ 10-bo'lim + §8.4 ko'rish cheklovi.

    `can_see_all=False` bo'lsa faqat shu adminga biriktirilgan (yoki hali
    hech kimga biriktirilmagan) mijozlarning case'lari hisoblanadi —
    `list_cases_by_statuses` dagi bilan bir xil qoida.
    """

    def scoped(stmt):
        if can_see_all:
            return stmt
        return visible_to(
            stmt.join(User, Case.user_id == User.id), viewer_admin_id, can_see_all
        )

    # SQLite CURRENT_TIMESTAMP (created_at ustuni) doim UTC — mahalliy sana
    # bilan solishtirsak, UTC+5 kabi zonalarda kuning bir necha soatida
    # "bugungi" hisob noto'g'ri chiqadi. Shuning uchun UTC sanadan foydalanamiz.
    today_start = datetime.datetime.combine(datetime.datetime.utcnow().date(), datetime.time.min)
    today_count = (
        await session.execute(
            scoped(select(func.count()).select_from(Case)).where(
                Case.created_at >= today_start
            )
        )
    ).scalar_one()

    status_rows = (
        await session.execute(
            scoped(select(Case.status, func.count()).select_from(Case)).group_by(Case.status)
        )
    ).all()
    by_status = {status.value: count for status, count in status_rows}

    problem_count = (
        await session.execute(
            scoped(select(func.count()).select_from(Case)).where(
                Case.status.in_(PROBLEM_STATUSES)
            )
        )
    ).scalar_one()

    return Stats(today_count=today_count, by_status=by_status, problem_count=problem_count)
