import datetime

from sqlalchemy import select

from core.logic.bot_pool import BotPoolManager, ensure_bots_seeded
from core.models import Bot


async def test_acquire_returns_free_bot_and_marks_busy(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["bot1", "bot2"])

    pool = BotPoolManager()
    async with session_factory() as session:
        bot = await pool.acquire(session, case_id=1)
        assert bot is not None
        assert bot.is_busy is True
        assert bot.current_case_id == 1


async def test_acquire_when_all_busy_queues_case(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["bot1"])

    pool = BotPoolManager()
    async with session_factory() as session:
        first = await pool.acquire(session, case_id=1)
        assert first is not None

        second = await pool.acquire(session, case_id=2)
        assert second is None
        assert pool.queue_length == 1


async def test_release_frees_bot_and_dispatches_queued_case(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["bot1"])

    assigned: list[tuple[int, int]] = []

    async def on_assigned(case_id: int, bot_id: int) -> None:
        assigned.append((case_id, bot_id))

    pool = BotPoolManager(on_assigned=on_assigned)
    async with session_factory() as session:
        bot = await pool.acquire(session, case_id=1)
        queued = await pool.acquire(session, case_id=2)
        assert queued is None

        await pool.release(session, bot.id)

        assert pool.queue_length == 0
        assert assigned == [(2, bot.id)]

        refreshed = await session.get(Bot, bot.id)
        assert refreshed.is_busy is True
        assert refreshed.current_case_id == 2
        assert refreshed.total_processed == 1


async def test_lru_prefers_never_used_bot_over_recently_used(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["bot1", "bot2"])

    pool = BotPoolManager()
    async with session_factory() as session:
        # bot1 ni band qilib, darhol bo'shatamiz -> last_used_at endi to'ldiriladi.
        bot1 = await pool.acquire(session, case_id=1)
        await pool.release(session, bot1.id)

        # bot2 hali umuman ishlatilmagan (last_used_at NULL) -> u birinchi tanlanishi kerak.
        next_bot = await pool.acquire(session, case_id=2)
        assert next_bot.username == "bot2"


async def test_lru_picks_oldest_used_bot_first(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["bot1", "bot2"])
        result = await session.execute(select(Bot).order_by(Bot.username))
        bot1, bot2 = result.scalars().all()
        bot1.last_used_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
        bot2.last_used_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        await session.commit()

    pool = BotPoolManager()
    async with session_factory() as session:
        chosen = await pool.acquire(session, case_id=1)
        assert chosen.username == "bot1"  # eng uzoq ishlatilmagan
