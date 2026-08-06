import asyncio
import datetime

from sqlalchemy import select

from core.logic.bot_pool import BotPoolManager, add_bot, ensure_bots_seeded
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


async def test_release_does_not_hold_lock_during_on_assigned(session_factory):
    """Audit J-1 — avval `on_assigned` (sekin bot-RPC bo'lishi mumkin)
    `self._lock` ushlab turilgan holda chaqirilardi, shuning uchun boshqa,
    BUTUNLAY BO'SH bir botga tegishli `acquire()` ham bloklanardi. Endi
    qulf faqat DB-yozish davomida ushlanadi."""
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["busy_bot"])

    on_assigned_started = asyncio.Event()
    release_on_assigned = asyncio.Event()

    async def slow_on_assigned(case_id: int, bot_id: int) -> None:
        on_assigned_started.set()
        await release_on_assigned.wait()  # atayin uzoq davom ettiriladi

    pool = BotPoolManager(on_assigned=slow_on_assigned)
    async with session_factory() as session:
        busy_bot = (
            await session.execute(select(Bot).where(Bot.username == "busy_bot"))
        ).scalars().first()
        # Yagona bot band qilinadi, ikkinchi case navbatga tushadi (bot yo'q).
        acquired = await pool.acquire(session, case_id=1)
        assert acquired.username == "busy_bot"
        queued = await pool.acquire(session, case_id=2)
        assert queued is None
        assert pool.queue_length == 1

        # free_bot navbatdagi case2ga EMAS, quyidagi bir vaqtdagi acquire()
        # uchun mo'ljallangan — shuning uchun LRU uni ikkinchi o'ringa
        # qo'yishi uchun `last_used_at`ni ataylab kelajakka o'rnatamiz
        # (busy_bot release()da "hozir" deb belgilanadi, bu esa undan eski
        # — LRU eng eskisini tanlagani uchun busy_bot navbatdagi case2ni oladi).
        free_bot = await add_bot(session, "free_bot")
        free_bot.last_used_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        await session.commit()

    async def do_release():
        async with session_factory() as session:
            await pool.release(session, busy_bot.id)

    release_task = asyncio.create_task(do_release())
    await asyncio.wait_for(on_assigned_started.wait(), timeout=2)

    # on_assigned hali "osilib" turibdi (release_on_assigned qo'yilmagan) —
    # shu paytda BUTUNLAY BOSHQA (hali hech qachon ishlatilmagan) botga
    # acquire() darhol qaytishi kerak, qulf tufayli kutib qolmasligi kerak.
    async with session_factory() as session:
        other = await asyncio.wait_for(pool.acquire(session, case_id=3), timeout=1)
    assert other is not None
    assert other.username == "free_bot"

    release_on_assigned.set()
    await asyncio.wait_for(release_task, timeout=2)


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
