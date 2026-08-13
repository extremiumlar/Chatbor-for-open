"""TZ v2 B-3 — CheckEngine (navbat/drip/kesh/javob/stall) va JobPoller testlari."""

import datetime
import json

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.check_engine import CheckEngine
from core.logic.check_patterns import CheckCategory, add_pattern
from core.logic.job_poller import JobPoller
from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import set_checker_account, set_group_chat_id
from core.models import (
    Admin,
    Case,
    CheckRequest,
    CheckResult,
    CheckTrigger,
    JobKind,
    ScheduledJob,
)

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


class FakeSender:
    """send_to_checker o'rnini bosadi — yuborilganlarni yozib boradi."""

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[int, str]] = []
        self.fail = fail
        self._next_id = 1000

    async def __call__(self, admin_id: int, text: str) -> int | None:
        if self.fail:
            return None
        self.sent.append((admin_id, text))
        self._next_id += 1
        return self._next_id


async def _seed_ready(session_factory):
    """Admin + shablonlar + tekshiruvchi — dvigatel 'tayyor' holatga keladi."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        await set_checker_account(session, "checker_user")


async def _open_case_with_screenshots(session_factory, tg_id=TG_ID, phone=PHONE):
    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, tg_id, "u", "M", phone)
    async with session_factory() as session:
        await set_group_chat_id(session, -100555)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", tg_id, [1], 1)
    return outcome.case


def _make_engine(session_factory, sender=None, alert=None):
    return CheckEngine(
        session_factory=session_factory,
        alert_sink=alert or _noop_alert,
        send_to_checker=sender or FakeSender(),
    )


# --------------------------------------------------------------------------- #
# request_check
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_request_check_queues_and_cancels_check_due(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)

    msg = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "navbatga" in msg
    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        assert db_case.status == CaseStatus.CHECK_QUEUED
        # §6.1 b — qo'lda /check avtomatik taymerni bekor qiladi.
        open_due = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.CHECK_DUE,
                        ScheduledJob.done_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert open_due == []


@pytest.mark.asyncio
async def test_request_check_no_duplicate(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)

    await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)
    msg = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "allaqachon" in msg
    async with session_factory() as session:
        requests = (await session.execute(select(CheckRequest))).scalars().all()
    assert len(requests) == 1


# --------------------------------------------------------------------------- #
# drip_tick
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_drip_sends_one_and_marks_sent(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    sender = FakeSender()
    engine = _make_engine(session_factory, sender=sender)
    await engine.request_check(case.id, CheckTrigger.AUTO)

    sent = await engine.drip_tick()

    assert sent == 1
    assert sender.sent == [(ADMIN_ID, f"+{PHONE}")]
    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        db_case = await session.get(Case, case.id)
        stall_jobs = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.STALLED_ALERT
                    )
                )
            )
            .scalars()
            .all()
        )
    assert req.sent_at is not None
    assert req.sent_message_id == 1001
    assert db_case.status == CaseStatus.CHECK_SENT
    assert len(stall_jobs) == 1  # javobsizlik nazorati rejalandi


@pytest.mark.asyncio
async def test_drip_flushes_all_queued_at_once(session_factory):
    """Foydalanuvchi qarori (2026-08-13): tezlik cheklovi YO'Q — navbatdagi
    barcha so'rovlar bitta tick'da ketadi (tekshiruvchi istalgancha qabul
    qiladi)."""
    await _seed_ready(session_factory)
    case1 = await _open_case_with_screenshots(session_factory)
    case2 = await _open_case_with_screenshots(
        session_factory, tg_id=222, phone="998907654321"
    )
    sender = FakeSender()
    engine = _make_engine(session_factory, sender=sender)
    await engine.request_check(case1.id, CheckTrigger.AUTO)
    await engine.request_check(case2.id, CheckTrigger.AUTO)

    assert await engine.drip_tick() == 2  # ikkalasi birdan
    assert await engine.drip_tick() == 0  # navbat bo'sh
    assert len(sender.sent) == 2

    # Ko'p ochiq so'rovda oddiy "bor" ENG ESKISIGA bog'lanadi (FIFO).
    await engine.handle_checker_reply(ADMIN_ID, "bor")
    async with session_factory() as session:
        req1 = (
            (await session.execute(select(CheckRequest).order_by(CheckRequest.id)))
            .scalars()
            .first()
        )
    assert req1.result == CheckResult.PASSED


@pytest.mark.asyncio
async def test_drip_not_ready_without_checker(session_factory):
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        # tekshiruvchi belgilanmagan!
    case = await _open_case_with_screenshots(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(session_factory, alert=capture)
    await engine.request_check(case.id, CheckTrigger.AUTO)

    assert await engine.drip_tick() == 0
    assert await engine.drip_tick() == 0
    # Alert faqat bir marta (spam yo'q).
    assert len([a for a in alerts if "ishga tushmadi" in a]) == 1


# --------------------------------------------------------------------------- #
# handle_checker_reply — bog'lash va tanish
# --------------------------------------------------------------------------- #


async def _sent_request(session_factory, engine, case):
    await engine.request_check(case.id, CheckTrigger.AUTO)
    await engine.drip_tick()
    async with session_factory() as session:
        return (
            (
                await session.execute(
                    select(CheckRequest).order_by(CheckRequest.id.desc())
                )
            )
            .scalars()
            .first()
        )


@pytest.mark.asyncio
async def test_reply_passed_updates_case(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(ADMIN_ID, "bazada bor ekan")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        db_case = await session.get(Case, case.id)
    assert req.result == CheckResult.PASSED
    assert db_case.status == CaseStatus.PASSED


@pytest.mark.asyncio
async def test_reply_failed(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(ADMIN_ID, "bunday nomer yo'q")

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
    assert db_case.status == CaseStatus.FAILED


@pytest.mark.asyncio
async def test_unrecognized_reply_waits(session_factory):
    """6.4.5 — "bir daqiqa" kabi javob: kutiladi, natija yozilmaydi."""
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(ADMIN_ID, "bir daqiqa kutib turing")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
    assert req.replied_at is None  # hali ochiq
    assert "bir daqiqa" in req.raw_reply  # jurnal uchun saqlandi

    # Keyingi xabar taniladi.
    await engine.handle_checker_reply(ADMIN_ID, "bor")
    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
    assert req.result == CheckResult.PASSED


@pytest.mark.asyncio
async def test_reply_bound_by_last4_digits(session_factory):
    """6.4.5 2-ustuvorlik — "...4567 bor" oxirgi 4 raqam bo'yicha bog'lanadi."""
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(ADMIN_ID, "901234567 bor")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
    assert req.result == CheckResult.PASSED


@pytest.mark.asyncio
async def test_reply_bound_by_reply_to(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    req = await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(
        ADMIN_ID, "bor", reply_to_msg_id=req.sent_message_id
    )

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
    assert db_case.status == CaseStatus.PASSED


@pytest.mark.asyncio
async def test_ambiguous_reply_needs_admin(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    engine = _make_engine(session_factory)
    await _sent_request(session_factory, engine, case)

    await engine.handle_checker_reply(ADMIN_ID, "bor yoki yo'q bilmadim")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        db_case = await session.get(Case, case.id)
    assert req.result == CheckResult.UNRECOGNIZED
    assert db_case.status == CaseStatus.NEEDS_ADMIN


@pytest.mark.asyncio
async def test_no_open_request_reply_ignored(session_factory):
    await _seed_ready(session_factory)
    engine = _make_engine(session_factory)
    await engine.handle_checker_reply(ADMIN_ID, "bor")  # xato bermasligi kifoya


# --------------------------------------------------------------------------- #
# Kesh (6.6)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cache_reuses_recent_result(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    sender = FakeSender()
    engine = _make_engine(session_factory, sender=sender)
    await _sent_request(session_factory, engine, case)
    await engine.handle_checker_reply(ADMIN_ID, "bor")

    # Xuddi shu nomer boshqa akkauntdan — yangi case... shubhali bo'ladi.
    # Kesh testi uchun o'sha case'ni qayta so'raymiz: PASSED bo'lgani uchun
    # yangi so'rov... — real ssenariy: boshqa mijoz-case, bir xil nomer.
    # Soddaroq: case statusini qo'lda ochiq holatga qaytarib qayta so'raymiz.
    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.SCREENSHOTS_SENT
        await session.commit()

    msg = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "Kesh" in msg
    assert len(sender.sent) == 1  # tekshiruvchiga QAYTA yuborilmadi
    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
    assert db_case.status == CaseStatus.PASSED


@pytest.mark.asyncio
async def test_recheck_after_failed_bypasses_cache(session_factory):
    """§6.1 a4 — FAILED'dan keyin admin /check qilsa — HAQIQIY qayta tekshiruv."""
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    sender = FakeSender()
    engine = _make_engine(session_factory, sender=sender)
    await _sent_request(session_factory, engine, case)
    await engine.handle_checker_reply(ADMIN_ID, "yo'q")

    msg = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "navbatga" in msg
    async with session_factory() as session:
        requests = (
            (await session.execute(select(CheckRequest).order_by(CheckRequest.id)))
            .scalars()
            .all()
        )
    assert requests[1].is_recheck is True


# --------------------------------------------------------------------------- #
# Stall (6.5) va poller
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_stalled_alert_via_poller(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(session_factory, alert=capture)
    await _sent_request(session_factory, engine, case)

    # Stall jobning muddatini o'tgan qilib qo'yamiz.
    async with session_factory() as session:
        job = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.STALLED_ALERT
                    )
                )
            )
            .scalars()
            .first()
        )
        job.due_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        await session.commit()

    poller = JobPoller(session_factory, engine, capture, poll_seconds=999)
    await poller.tick()

    assert any("javob bermayapti" in a for a in alerts)
    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        req = (await session.execute(select(CheckRequest))).scalars().first()
    assert db_case.status == CaseStatus.CHECK_STALLED
    assert req.replied_at is None  # so'rov hamon ochiq — yo'qolmagan


@pytest.mark.asyncio
async def test_poller_check_due_triggers_auto_check(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)

    # CHECK_DUE muddatini o'tkazamiz.
    async with session_factory() as session:
        job = (
            (
                await session.execute(
                    select(ScheduledJob).where(ScheduledJob.kind == JobKind.CHECK_DUE)
                )
            )
            .scalars()
            .first()
        )
        job.due_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        await session.commit()

    engine = _make_engine(session_factory)
    poller = JobPoller(session_factory, engine, _noop_alert, poll_seconds=999)
    await poller.tick()

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        requests = (await session.execute(select(CheckRequest))).scalars().all()
    assert db_case.status == CaseStatus.CHECK_QUEUED
    assert len(requests) == 1
    assert requests[0].trigger == CheckTrigger.AUTO


@pytest.mark.asyncio
async def test_poller_remind_two_variants_and_escalation(session_factory):
    """§6.1 a2 — kupon bor/yo'q — 2 xil matn; limitdan keyin superadmin."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)

    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(session_factory, alert=capture)
    poller = JobPoller(session_factory, engine, capture, poll_seconds=999)

    async def _fire_due_reminder():
        async with session_factory() as session:
            job = (
                (
                    await session.execute(
                        select(ScheduledJob).where(
                            ScheduledJob.kind == JobKind.REMIND_NO_SCREENSHOT,
                            ScheduledJob.done_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
            assert job is not None
            job.due_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
            await session.commit()
        await poller.tick()

    # 1-eslatma: kupon YO'Q — "ovozini ham olib qo'ying".
    await _fire_due_reminder()
    assert any("ovozini ham olib qo'ying" in a for a in alerts)

    # Kupon keladi — endi matn "rasm tashlashni unutdingiz" bo'ladi.
    await manager.handle_coupon_detected(TG_ID, "123456")
    await _fire_due_reminder()
    assert any("rasm tashlashni unutdingiz" in a for a in alerts)

    # 3-eslatma (limit=3) — keyin superadmin eskalatsiyasi.
    await _fire_due_reminder()
    assert any("javob bermadi" in a for a in alerts)
    async with session_factory() as session:
        db_case = await session.get(Case, outcome.case.id)
        open_jobs = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.REMIND_NO_SCREENSHOT,
                        ScheduledJob.done_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert db_case.status == CaseStatus.NUMBER_RECEIVED  # case OCHIQ qoladi
    assert open_jobs == []  # eslatmalar tugadi


@pytest.mark.asyncio
async def test_poller_remind_stops_after_screenshots(session_factory):
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()
        await set_group_chat_id(session, -100555)

    manager = ManualCaseManager(session_factory=session_factory)
    await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)

    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(session_factory, alert=capture)
    poller = JobPoller(session_factory, engine, capture, poll_seconds=999)
    # Yopilgan eslatma jobi bor, ochiq REMIND yo'q — tick hech narsa qilmaydi.
    done = await poller.tick()
    assert not any("eslatma" in a for a in alerts)
    assert done == 0


# --------------------------------------------------------------------------- #
# B-6 — nofaol admin muzlatish (§4.2b) va drip spam-guard
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_drip_skips_inactive_admin(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    sender = FakeSender()
    engine = _make_engine(session_factory, sender=sender)
    await engine.request_check(case.id, CheckTrigger.AUTO)

    async with session_factory() as session:
        admin = await session.get(Admin, ADMIN_ID)
        admin.is_active = False
        await session.commit()

    assert await engine.drip_tick() == 0
    assert sender.sent == []  # muzlatilgan — yuborilmadi

    # Admin qaytdi — so'rov navbatdan davom etadi.
    async with session_factory() as session:
        admin = await session.get(Admin, ADMIN_ID)
        admin.is_active = True
        await session.commit()
    assert await engine.drip_tick() == 1
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_drip_send_failure_alerts_once(session_factory):
    await _seed_ready(session_factory)
    case = await _open_case_with_screenshots(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(
        session_factory, sender=FakeSender(fail=True), alert=capture
    )
    await engine.request_check(case.id, CheckTrigger.AUTO)

    await engine.drip_tick()
    await engine.drip_tick()
    await engine.drip_tick()

    assert len([a for a in alerts if "yuborilmadi" in a]) == 1  # spam yo'q


@pytest.mark.asyncio
async def test_reminder_frozen_for_inactive_admin(session_factory):
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz", is_active=False))
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)

    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    engine = _make_engine(session_factory, alert=capture)
    poller = JobPoller(session_factory, engine, capture, poll_seconds=999)

    async with session_factory() as session:
        job = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == JobKind.REMIND_NO_SCREENSHOT
                    )
                )
            )
            .scalars()
            .first()
        )
        job.due_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        await session.commit()

    await poller.tick()
    assert not any("eslatma" in a for a in alerts)  # muzlatilgan — jim
