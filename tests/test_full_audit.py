"""To'liq sifat tekshiruvi (audit) — TZ v2 bo'yicha qamrov bo'shliqlari.

Mavjud 217 test qoplamagan ssenariylar: mijoz kirishlarining turli
yozilishlari, nomer+kupon BITTA xabarda, FAILED'dan keyin qayta yuborish,
restart chidamliligi, poller xato chidamliligi, javob bog'lashning chekka
holatlari, ko'p qatorli/apostrofli javoblar.
"""

import datetime

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.check_engine import CheckEngine
from core.logic.check_patterns import CheckCategory, add_pattern, classify
from core.logic.coupon import extract_coupon
from core.logic.job_poller import JobPoller
from core.logic.manual_case import ManualCaseManager
from core.logic.phone import extract_phone
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import set_checker_account, set_group_chat_id
from core.models import (
    Admin,
    Case,
    CheckRequest,
    CheckTrigger,
    JobKind,
    ScheduledJob,
)

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
CODES = ["90", "91", "93", "94", "95", "97", "98", "99", "33", "88", "20"]


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


class FakeSender:
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
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_PASSED, "o'tdi")
        await add_pattern(session, CheckCategory.CHECK_PASSED, "~bazada bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        await set_checker_account(session, "checker")
        await set_group_chat_id(session, -100555)


# =========================================================================== #
# 1. MIJOZ — kirish matnlarining turli yozilishlari (sof funksiyalar)
# =========================================================================== #


def test_phone_written_many_ways():
    assert extract_phone("+998 90 123 45 67", CODES) == PHONE
    assert extract_phone("901234567", CODES) == PHONE
    assert extract_phone("998901234567", CODES) == PHONE
    assert extract_phone("mening nomerim 90-123-45-67 yozib oling", CODES) == PHONE
    assert extract_phone("(90) 123 45 67 shu nomer", CODES) == PHONE


def test_ordinary_chat_does_not_trigger():
    """Nomersiz/kuponsiz oddiy suhbat — tizim umuman qo'zg'almaydi."""
    for text in [
        "salom qalaysiz",
        "rahmat katta",  # raqamsiz
        "narxi 25000 so'm",  # 5 xonali — kupon emas
        "soat 15:30 da keldi",  # qisqa raqamlar
        "2026 yil 12 avgust",  # sana
    ]:
        assert extract_phone(text, CODES) is None, text
        assert extract_coupon(text) is None, text


def test_phone_and_coupon_in_same_message():
    """MUHIM: mijoz nomer va kuponni BITTA xabarda yuborishi odatiy hol.

    Kupon regexi 6-lik uzilmagan raqam talab qiladi — 9/12 xonali nomer
    ichidan yolg'on kupon olinmasligi ham shu yerda tekshiriladi.
    """
    text = "901234567 kuponim 123456"
    assert extract_phone(text, CODES) == PHONE
    assert extract_coupon(text) == "123456"

    # Nomer ichidan kupon "topilmasligi" kerak.
    assert extract_coupon("901234567") is None
    assert extract_coupon("998901234567") is None

    # Bo'shliqli nomer bo'laklari ham kupon emas.
    assert extract_coupon("+998 90 123 45 67") is None


@pytest.mark.asyncio
async def test_combined_message_flow_saves_both(session_factory):
    """Relay tartibi: avval nomer, keyin O'SHA matndan kupon — ikkovi saqlanadi
    (BUG-1 regressiyasi: avval kupon yo'qolib qolardi, chunki relay phone
    topilishi bilan return qilardi)."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    text = "nomerim 901234567 kupon 123456"

    phone = extract_phone(text, CODES)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", phone)
    coupon = extract_coupon(text)
    if coupon is not None:
        await manager.handle_coupon_detected(TG_ID, coupon)

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
    assert case.phone == PHONE
    assert case.coupon == "123456"


# =========================================================================== #
# 2. MIJOZ — FAILED'dan keyin qayta yuborish (§6.1 a4)
# =========================================================================== #


@pytest.mark.asyncio
async def test_failed_then_resend_opens_new_case_with_coupon_carried(
    session_factory,
):
    """FAILED'dan keyin mijoz o'sha nomerni qayta tashlasa: yangi sikl ochiladi
    (admin qaror qiladi), va MUHIMI — eski case'dagi kupon yangi case'ga
    ko'chadi (BUG-2 regressiyasi: aks holda rasmsizlik eslatmasi noto'g'ri
    variantda — "ovozini ham olib qo'ying" — chiqardi, vaholanki mijoz
    allaqachon ovoz bergan)."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    first = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    await manager.handle_coupon_detected(TG_ID, "123456")

    async with session_factory() as session:
        case = await session.get(Case, first.case.id)
        case.status = CaseStatus.FAILED
        await session.commit()

    second = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)

    assert second.case.id != first.case.id  # yangi sikl
    assert second.case.status == CaseStatus.NUMBER_RECEIVED
    assert second.case.coupon == "123456"  # kupon ko'chdi
    assert second.customer_text is None  # mijozga avtomatik hech narsa


# =========================================================================== #
# 3. TIZIM — restart chidamliligi
# =========================================================================== #


@pytest.mark.asyncio
async def test_restart_overdue_jobs_processed_by_fresh_instances(session_factory):
    """"Restart" simulyatsiyasi: eski jarayon o'lgan (obyektlar yo'q),
    scheduled_jobs bazada. YANGI engine/poller nusxalari ko'tarilib,
    muddati o'tgan ishlarni bajarishi shart."""
    await _seed_ready(session_factory)

    # Jarayon-1: case + rasm (CHECK_DUE rejalanadi), boshqa mijozda rasmsiz
    # case (REMIND rejalanadi).
    manager = ManualCaseManager(session_factory=session_factory)
    c1 = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u1", "M1", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)
    c2 = await manager.handle_phone_detected(
        ADMIN_ID, 222, "u2", "M2", "998907654321"
    )

    # "O'chirib yoqish" — vaqt o'tdi, hamma job muddati keldi.
    async with session_factory() as session:
        for job in (await session.execute(select(ScheduledJob))).scalars().all():
            job.due_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        await session.commit()

    # Jarayon-2: butunlay yangi obyektlar.
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    sender = FakeSender()
    engine2 = CheckEngine(
        session_factory=session_factory, alert_sink=capture, send_to_checker=sender
    )
    poller2 = JobPoller(session_factory, engine2, capture, poll_seconds=999)
    done = await poller2.tick()

    assert done >= 2
    async with session_factory() as session:
        case1 = await session.get(Case, c1.case.id)
        requests = (await session.execute(select(CheckRequest))).scalars().all()
    # CHECK_DUE ishladi — tekshiruv navbatga tushdi.
    assert case1.status == CaseStatus.CHECK_QUEUED
    assert len(requests) == 1
    # REMIND ishladi — eslatma ketdi (kupon yo'q varianti).
    assert any("ovozini ham olib qo'ying" in a for a in alerts)


# =========================================================================== #
# 4. TIZIM — poller xato chidamliligi
# =========================================================================== #


@pytest.mark.asyncio
async def test_poller_failure_retries_then_closes_with_alert(session_factory):
    await _seed_ready(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    class ExplodingEngine:
        async def request_check(self, *a, **k):
            raise RuntimeError("sun'iy xato")

        async def handle_stalled(self, *a, **k):
            raise RuntimeError("sun'iy xato")

    # SCREENSHOTS_SENT holatidagi case bilan CHECK_DUE job.
    manager = ManualCaseManager(session_factory=session_factory)
    c = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)

    poller = JobPoller(session_factory, ExplodingEngine(), capture, poll_seconds=999)

    for round_no in range(5):
        async with session_factory() as session:
            jobs = (
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
            if not jobs:
                break
            for job in jobs:
                job.due_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=5)
            await session.commit()
        await poller.tick()

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
    assert job.attempts == 5
    assert job.done_at is not None  # yopildi — cheksiz sikl yo'q
    assert any("KRITIK" in a and "bajarilmadi" in a for a in alerts)


# =========================================================================== #
# 5. TIZIM — javob bog'lashning chekka holatlari (unit)
# =========================================================================== #


def _req(rid: int, phone: str, msg_id: int) -> CheckRequest:
    r = CheckRequest(
        case_id=rid, phone=phone, requested_by_admin_id=1, trigger=CheckTrigger.AUTO
    )
    r.id = rid
    r.sent_message_id = msg_id
    return r


def test_bind_reply_priorities():
    engine = CheckEngine.__new__(CheckEngine)  # sof _bind_reply uchun
    r1 = _req(1, "998901111234", 100)
    r2 = _req(2, "998902221234", 200)  # oxirgi 4 raqami BIR XIL (1234)
    r3 = _req(3, "998903334567", 300)

    # 1-ustuvorlik: reply aniq bog'laydi (last4 to'qnashuviga qaramay).
    assert engine._bind_reply([r1, r2, r3], "bor", reply_to_msg_id=200) is r2

    # 2-ustuvorlik: last4 yagona mosda ishlaydi.
    assert engine._bind_reply([r1, r3], "3334567 bor", reply_to_msg_id=None) is r3

    # last4 IKKI so'rovga mos — taxmin qilinmaydi (None -> alert).
    assert engine._bind_reply([r1, r2], "1234 bor", reply_to_msg_id=None) is None

    # 3-ustuvorlik: raqamsiz javob — ENG ESKI ochiq so'rovga (FIFO).
    assert engine._bind_reply([r1], "bor", reply_to_msg_id=None) is r1

    # Raqamsiz javob, bir nechta ochiq — eng eskisiga (tekshiruvchi tartib
    # bilan javob beradi; cheklov olib tashlangan, 2026-08-13).
    assert engine._bind_reply([r1, r2], "bor", reply_to_msg_id=None) is r1

    # Raqam bor lekin hech biriga mos emas -> FIFO qoidasiga tushadi.
    assert engine._bind_reply([r1], "9999 bor", reply_to_msg_id=None) is r1


# =========================================================================== #
# 6. TIZIM — javob matnlarining chekka ko'rinishlari
# =========================================================================== #


def test_reply_text_edge_cases():
    patterns = {
        CheckCategory.CHECK_PASSED: ["bor", "o'tdi", "~bazada bor", "=✅"],
        CheckCategory.CHECK_FAILED: ["yo'q", "o'tmadi"],
        CheckCategory.CHECK_ERROR: ["xato"],
    }
    # Ko'p qatorli javob.
    assert (
        classify("Tekshirdim.\nBu nomer bazada bor ekan.", patterns)
        == CheckCategory.CHECK_PASSED
    )
    # Apostrof variantlari (oʻ / o` / o').
    assert classify("oʻtdi", patterns) == CheckCategory.CHECK_PASSED
    assert classify("o`tmadi", patterns) == CheckCategory.CHECK_FAILED
    # Katta-kichik harf.
    assert classify("YO'Q BUNDAY NOMER", patterns) == CheckCategory.CHECK_FAILED
    # Emoji javob.
    assert classify("✅", patterns) == CheckCategory.CHECK_PASSED
    # Bo'sh / faqat bo'shliq — kutiladi.
    assert classify("", patterns) is None
    assert classify("   \n  ", patterns) is None
    # "borligi" so'z ichida — mos EMAS (butun so'z qoidasi).
    assert classify("borligi aniqlanmadi", patterns) is None


@pytest.mark.asyncio
async def test_whitespace_reply_keeps_request_open(session_factory):
    await _seed_ready(session_factory)
    manager = ManualCaseManager(session_factory=session_factory)
    c = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)

    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=FakeSender(),
    )
    await engine.request_check(c.case.id, CheckTrigger.AUTO)
    await engine.drip_tick()

    await engine.handle_checker_reply(ADMIN_ID, "   ")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
    assert req.replied_at is None  # so'rov hamon ochiq
