"""TZ v2 B-5 — statistika moduli va kunlik hisobot testlari."""

import datetime

import pytest
from sqlalchemy import select

from core.logic.check_engine import CheckEngine
from core.logic.check_patterns import CheckCategory, add_pattern
from core.logic.job_poller import JobPoller
from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import set_checker_account, set_group_chat_id
from core.logic.v2_stats import (
    ensure_daily_report_scheduled,
    gather_v2_stats,
    next_daily_report_due_utc,
    render_daily_group_report,
    render_daily_superadmin_report,
    render_stats,
    tashkent_day_start_utc,
)
from core.models import Admin, CheckTrigger, JobKind, ScheduledJob


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


class FakeSender:
    def __init__(self):
        self._next_id = 1000

    async def __call__(self, admin_id, text):
        self._next_id += 1
        return self._next_id


async def _seed_two_admins_with_activity(session_factory):
    """Aziz: 2 nomer, 1 partiya, 1 tekshiruv (PASSED). Bekzod: 1 nomer."""
    async with session_factory() as session:
        session.add(Admin(id=1, tg_user_id=901, name="Aziz"))
        session.add(Admin(id=2, tg_user_id=902, name="Bekzod"))
        await session.commit()
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        await set_checker_account(session, "checker")
        await set_group_chat_id(session, -100555)

    manager = ManualCaseManager(session_factory=session_factory)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=FakeSender(),
    )

    # Aziz — to'liq sikl.
    c1 = await manager.handle_phone_detected(1, 111, "u1", "M1", "998901111111")
    await flow.register_batch(1, "Aziz", 111, [1, 2], 2)
    await engine.request_check(c1.case.id, CheckTrigger.AUTO)
    await engine.drip_tick()
    await engine.handle_checker_reply(1, "bor")

    # Aziz — ikkinchi nomer (rasm tashlanmagan).
    await manager.handle_phone_detected(1, 112, "u2", "M2", "998902222222")

    # Bekzod — faqat nomer.
    await manager.handle_phone_detected(2, 222, "u3", "M3", "998903333333")

    return engine


@pytest.mark.asyncio
async def test_gather_stats_per_admin(session_factory):
    await _seed_two_admins_with_activity(session_factory)
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=1)

    async with session_factory() as session:
        report = await gather_v2_stats(session, since)

    by_name = {r.admin_name: r for r in report.rows}
    aziz, bekzod = by_name["Aziz"], by_name["Bekzod"]

    assert aziz.cases == 2
    assert aziz.batches == 1
    assert aziz.images == 2
    assert aziz.checks_auto == 1
    assert aziz.passed == 1
    assert aziz.conversion_pct == 100
    assert aziz.awaiting_screenshot == 1  # ikkinchi nomer rasmsiz
    assert aziz.avg_reply_minutes is not None

    assert bekzod.cases == 1
    assert bekzod.checked == 0
    assert bekzod.conversion_pct is None

    assert report.totals.cases == 3
    assert report.totals.passed == 1


@pytest.mark.asyncio
async def test_gather_stats_admin_filter(session_factory):
    """TZ v2 8.4 — oddiy admin faqat o'z raqamlarini oladi."""
    await _seed_two_admins_with_activity(session_factory)
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=1)

    async with session_factory() as session:
        report = await gather_v2_stats(session, since, admin_id=2)

    assert [r.admin_name for r in report.rows] == ["Bekzod"]
    assert report.totals.cases == 1
    assert report.totals.passed == 0


@pytest.mark.asyncio
async def test_render_outputs(session_factory):
    await _seed_two_admins_with_activity(session_factory)
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    async with session_factory() as session:
        report = await gather_v2_stats(session, since)

    admin_text = render_stats(report, "Sinov")
    group_text = render_daily_group_report(report, "12.08.2026")
    super_text = render_daily_superadmin_report(report, "12.08.2026")

    assert "Sinov" in admin_text and "Aziz" in admin_text
    assert "12.08.2026 yakuni" in group_text
    assert "✅ 1 o'tdi" in group_text
    assert "Superadmin qo'shimchasi" in super_text
    assert "Bekzod" in group_text


def test_tashkent_day_start():
    # 2026-08-11 20:30 UTC = 12-avgust 01:30 Toshkent -> kun boshi 12-avg 00:00
    # Toshkent = 11-avg 19:00 UTC.
    now = datetime.datetime(2026, 8, 11, 20, 30)
    assert tashkent_day_start_utc(now) == datetime.datetime(2026, 8, 11, 19, 0)
    # 7 kunlik davr uchun days_back.
    assert tashkent_day_start_utc(now, days_back=6) == datetime.datetime(2026, 8, 5, 19, 0)


def test_next_daily_report_due():
    # 12:00 Toshkent (07:00 UTC) -> bugun 21:00 Toshkent = 16:00 UTC.
    now = datetime.datetime(2026, 8, 12, 7, 0)
    assert next_daily_report_due_utc(now) == datetime.datetime(2026, 8, 12, 16, 0)
    # 22:00 Toshkent (17:00 UTC) -> ertaga.
    now = datetime.datetime(2026, 8, 12, 17, 0)
    assert next_daily_report_due_utc(now) == datetime.datetime(2026, 8, 13, 16, 0)
    # Noto'g'ri format -> 21:00 standart.
    assert next_daily_report_due_utc(
        datetime.datetime(2026, 8, 12, 7, 0), "xx"
    ) == datetime.datetime(2026, 8, 12, 16, 0)


@pytest.mark.asyncio
async def test_ensure_daily_report_scheduled_idempotent(session_factory):
    async with session_factory() as session:
        await ensure_daily_report_scheduled(session)
        await ensure_daily_report_scheduled(session)
        jobs = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.DAILY_REPORT
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_poller_daily_report_fires_and_reschedules(session_factory):
    engine = await _seed_two_admins_with_activity(session_factory)
    fired: list[bool] = []

    async def report_hook():
        fired.append(True)

    async with session_factory() as session:
        session.add(
            ScheduledJob(
                kind=JobKind.DAILY_REPORT,
                due_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=1),
            )
        )
        await session.commit()

    poller = JobPoller(
        session_factory, engine, _noop_alert, poll_seconds=999, daily_report=report_hook
    )
    await poller.tick()

    assert fired == [True]
    async with session_factory() as session:
        jobs = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.DAILY_REPORT
                    )
                )
            )
            .scalars()
            .all()
        )
    done = [j for j in jobs if j.done_at is not None]
    pending = [j for j in jobs if j.done_at is None]
    assert len(done) == 1
    assert len(pending) == 1  # keyingi kun rejalandi
    assert pending[0].due_at > datetime.datetime.utcnow()
