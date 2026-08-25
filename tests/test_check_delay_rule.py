"""QOIDA — tekshiruv rasm tashlangandan 70 daqiqa o'tmasdan ishga tushmaydi.

Sabab texnik emas, tashqi tizimda: ovoz tekshiruvchining bazasiga darhol
tushmaydi. Erta so'ralsa "bazada yo'q" javobi keladi va tizim buni O'TMADI
deb yozadi — mijozning ovozi aslida o'tgan bo'lsa ham.

Chegara IKKALA yo'lda ham amal qiladi (foydalanuvchi qarori):
  1. avtomatik — `get_check_delay_minutes` sozlamasi 70 dan past tusha
     olmaydi, CHECK_DUE taymeri shundan oladi;
  2. qo'lda `/check` — 70 daqiqa to'lmasa rad etiladi.
"""

import datetime

import pytest
from sqlalchemy import select

from core.logic.check_engine import CheckEngine
from core.logic.check_patterns import CheckCategory, add_pattern
from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import (
    MIN_CHECK_DELAY_MINUTES,
    CHECK_DELAY_KEY,
    get_check_delay_minutes,
    set_setting,
    set_checker_account,
    set_group_chat_id,
)
from core.models import Admin, CheckTrigger, ScreenshotBatch

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


class _FakeSender:
    def __init__(self):
        self.sent = []

    async def __call__(self, admin_id: int, text: str):
        self.sent.append((admin_id, text))
        return len(self.sent)


def test_the_rule_is_seventy_minutes():
    """1 soat 10 daqiqa = 70 daqiqa. Qiymat o'zgarib ketmasin."""
    assert MIN_CHECK_DELAY_MINUTES == 70


# --------------------------------------------------------------------------- #
# 1-qatlam: sozlama chegaradan past tusha olmaydi
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kiritilgan,kutilgan", [(0, 70), (10, 70), (69, 70), (70, 70)])
async def test_setting_cannot_go_below_the_floor(
    session_factory, kiritilgan, kutilgan
):
    async with session_factory() as session:
        await set_setting(session, CHECK_DELAY_KEY, str(kiritilgan))
        assert await get_check_delay_minutes(session) == kutilgan


@pytest.mark.parametrize("kiritilgan", [71, 90, 180])
async def test_setting_may_go_above_the_floor(session_factory, kiritilgan):
    """Chegara faqat PASTKI — kattaroq qilish mumkin."""
    async with session_factory() as session:
        await set_setting(session, CHECK_DELAY_KEY, str(kiritilgan))
        assert await get_check_delay_minutes(session) == kiritilgan


async def test_scheduled_check_uses_the_floor(session_factory):
    """Rasm tashlanganda rejalashtiriladigan CHECK_DUE ham chegaraga
    bo'ysunadi — sozlama past bo'lsa ham."""
    from core.models import JobKind, ScheduledJob
    from sqlalchemy import select

    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await set_setting(session, CHECK_DELAY_KEY, "5")  # ataylab juda kam
        await set_group_chat_id(session, -100555)
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)

    async with session_factory() as session:
        job = (
            await session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.kind == JobKind.CHECK_DUE,
                    ScheduledJob.done_at.is_(None),
                )
            )
        ).scalars().first()

    qolgan = (job.due_at - datetime.datetime.utcnow()).total_seconds() / 60
    assert 69 <= qolgan <= 71, f"taymer {qolgan:.0f} daqiqaga qo'yildi, 70 kutilgan"


# --------------------------------------------------------------------------- #
# 2-qatlam: qo'lda /check ham chegaraga bo'ysunadi
# --------------------------------------------------------------------------- #


async def _case_with_batch(session_factory, yosh_daqiqa: int):
    """Rasmi `yosh_daqiqa` daqiqa oldin tashlangan ochiq case."""
    async with session_factory() as session:
        if await session.get(Admin, ADMIN_ID) is None:
            session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await set_group_chat_id(session, -100555)
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        await set_checker_account(session, "checker_user")
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1], 1)

    async with session_factory() as session:
        batch = await session.get(ScreenshotBatch, decision.batch_id)
        batch.sent_at = datetime.datetime.utcnow() - datetime.timedelta(
            minutes=yosh_daqiqa
        )
        await session.commit()
    return outcome.case


@pytest.mark.parametrize("yosh", [0, 5, 30, 69])
async def test_manual_check_is_refused_before_the_limit(session_factory, yosh):
    """Eng xavfli yo'l: admin sabri chidamay darhol /check qiladi."""
    case = await _case_with_batch(session_factory, yosh)
    sender = _FakeSender()
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=sender,
    )

    javob = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "erta" in javob.lower()
    assert "70 daqiqa" in javob
    await engine.drip_tick()
    assert sender.sent == [], "erta bo'lsa ham tekshiruvchiga so'rov ketdi!"


@pytest.mark.parametrize("yosh", [70, 71, 200])
async def test_manual_check_allowed_after_the_limit(session_factory, yosh):
    case = await _case_with_batch(session_factory, yosh)
    sender = _FakeSender()
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=sender,
    )

    javob = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "erta" not in javob.lower()
    await engine.drip_tick()
    assert len(sender.sent) == 1


async def test_refusal_says_how_long_is_left(session_factory):
    """Admin nima qilishini bilishi kerak — qancha qolganini aytadi."""
    case = await _case_with_batch(session_factory, 50)
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=_FakeSender(),
    )

    javob = await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "20 daqiqa" in javob  # 70 - 50


async def test_auto_trigger_is_never_refused(session_factory):
    """AUTO ataylab tekshirilmaydi: vaqti kelib ishga tushgan CHECK_DUE
    ishi sekundlik farq tufayli rad etilsa, case abadiy tekshirilmay
    qolishi mumkin edi."""
    case = await _case_with_batch(session_factory, 0)   # hozirgina tashlangan
    sender = _FakeSender()
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=sender,
    )

    javob = await engine.request_check(case.id, CheckTrigger.AUTO, ADMIN_ID)

    assert "erta" not in javob.lower()
    await engine.drip_tick()
    assert len(sender.sent) == 1


async def test_case_without_screenshots_is_not_blocked(session_factory):
    """Rasm umuman tashlanmagan case'da cheklash mantiqsiz — kutiladigan
    rasm yo'q, va bloklash adminni ishlay olmaydigan holatga tushirardi."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await set_checker_account(session, "checker_user")
        await session.commit()

    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "M", PHONE)
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=_noop_alert,
        send_to_checker=_FakeSender(),
    )

    javob = await engine.request_check(outcome.case.id, CheckTrigger.MANUAL, ADMIN_ID)

    assert "erta" not in javob.lower()


# --------------------------------------------------------------------------- #
# Stall alerti: "javob bermadi" va "tanimadim" ni ajratishi kerak
# --------------------------------------------------------------------------- #


async def test_stall_alert_distinguishes_silence_from_unrecognized(session_factory):
    """Jonli tizimda 9 kun davomida natija chiqmagan va sabab noma'lum
    qolgan edi: tekshiruvchi javob berib turardi, shablonlar esa uni
    tanimasdi — alert esa "javob bermayapti" deb turardi."""
    from core.models import CheckRequest

    alerts: list[str] = []

    async def sink(message: str, important: bool = True) -> None:
        alerts.append(message)

    case = await _case_with_batch(session_factory, 120)
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=sink,
        send_to_checker=_FakeSender(),
    )
    await engine.request_check(case.id, CheckTrigger.MANUAL, ADMIN_ID)
    await engine.drip_tick()

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        request_id = req.id

    # (a) Umuman javob yo'q.
    alerts.clear()
    await engine.handle_stalled(request_id)
    assert any("javob bermayapti" in a for a in alerts)

    # (b) Javob keldi, lekin tanilmadi.
    async with session_factory() as session:
        req = await session.get(CheckRequest, request_id)
        req.raw_reply = "Kod bordi"
        await session.commit()
    alerts.clear()
    await engine.handle_stalled(request_id)

    ogoh = "\n".join(alerts)
    assert "TANIMADI" in ogoh, "tanilmagan javob 'javob bermadi' deb xabar qilindi"
    assert "Kod bordi" in ogoh, "admin javob matnini ko'rmaydi"
    assert "/unrecognized" in ogoh, "nima qilish kerakligi aytilmadi"
