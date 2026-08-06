"""Har bir tekshiruv-bot bilan almashinuv izi — TZ 11.5 (audit J-7)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import RelayDirection, RelayLog


async def log_relay(
    session: AsyncSession,
    direction: RelayDirection,
    payload: str,
    case_id: int | None = None,
    bot_id: int | None = None,
) -> None:
    session.add(RelayLog(case_id=case_id, bot_id=bot_id, direction=direction, payload=payload[:2000]))
    await session.commit()


async def relay_log_for_case(session: AsyncSession, case_id: int) -> list[RelayLog]:
    result = await session.execute(
        select(RelayLog).where(RelayLog.case_id == case_id).order_by(RelayLog.id)
    )
    return list(result.scalars().all())
