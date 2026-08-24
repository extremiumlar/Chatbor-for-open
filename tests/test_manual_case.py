"""TZ v2 B-1 — ManualCaseManager (nomer/kupon qabul) testlari."""

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.manual_case import ManualCaseManager
from core.models import Admin, Case, JobKind, ScheduledJob, User

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
OTHER_PHONE = "998907654321"


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


@pytest.fixture
def make_manager(session_factory):
    def _make(alert_sink=None, suspicious_alert_sink=None):
        kwargs = {}
        if alert_sink is not None:
            kwargs["alert_sink"] = alert_sink
        if suspicious_alert_sink is not None:
            kwargs["suspicious_alert_sink"] = suspicious_alert_sink
        return ManualCaseManager(session_factory=session_factory, **kwargs)

    return _make


async def _seed_admin(session_factory, admin_id: int = ADMIN_ID) -> None:
    async with session_factory() as session:
        session.add(Admin(id=admin_id, tg_user_id=900 + admin_id, name=f"admin{admin_id}"))
        await session.commit()


@pytest.mark.asyncio
async def test_new_phone_opens_case_with_admin_and_short_code(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()

    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "user1", "Mijoz", PHONE)

    assert outcome.customer_text is None  # tizim mijozga hech narsa yozmaydi
    assert outcome.case is not None
    assert outcome.case.status == CaseStatus.NUMBER_RECEIVED
    assert outcome.case.assigned_admin_id == ADMIN_ID
    assert outcome.case.short_code == f"C{outcome.case.id}"


@pytest.mark.asyncio
async def test_new_case_schedules_no_screenshot_reminder(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()

    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    async with session_factory() as session:
        jobs = (await session.execute(select(ScheduledJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].kind == JobKind.REMIND_NO_SCREENSHOT
    assert jobs[0].case_id == outcome.case.id
    assert jobs[0].done_at is None


@pytest.mark.asyncio
async def test_coupon_saved_as_signal_only_once(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    await manager.handle_coupon_detected(TG_ID, "123456")
    await manager.handle_coupon_detected(TG_ID, "999999")  # ikkinchisi e'tiborsiz

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
    assert case.coupon == "123456"
    assert case.coupon_at is not None


# --------------------------------------------------------------------------- #
# T-14 — kupon TO'G'RI case'ga yozilsin
#
# Jonli sinovda mijoz "907778899 kuponim 123456" yozdi. Yangi nomer rad
# etildi (boshqa case ochiq edi), lekin kupon ESKI case'ga yozilib qoldi.
# TZ §9.2 kuponni dalil deb belgilaydi — noto'g'ri nomerga bog'langan kupon
# dalilni ham, §6.1a2 dagi rasmsizlik eslatmasini ham buzadi.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_t14_coupon_with_another_phone_is_not_written_to_the_open_case(
    session_factory, make_manager
):
    """Ochiq case A turganda mijoz "B_nomer + kupon" yozsa, kupon A ga
    YOZILMASLIGI kerak."""
    await _seed_admin(session_factory)
    manager = make_manager()
    a = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    # OTHER_PHONE uchun case ochilmaydi (A hali ochiq) — kupon ham
    # hech qayerga yozilmasligi kerak.
    await manager.handle_coupon_detected(TG_ID, "123456", phone=OTHER_PHONE)

    async with session_factory() as session:
        case_a = await session.get(Case, a.case.id)
        cases = (await session.execute(select(Case))).scalars().all()
    assert case_a.coupon is None, "kupon boshqa nomerning case'iga yozilib ketdi"
    assert len(cases) == 1


@pytest.mark.asyncio
async def test_t14_coupon_with_matching_phone_is_saved(session_factory, make_manager):
    """Nomer o'sha case'niki bo'lsa — kupon yozilishi kerak."""
    await _seed_admin(session_factory)
    manager = make_manager()
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    await manager.handle_coupon_detected(TG_ID, "123456", phone=PHONE)

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
    assert case.coupon == "123456"
    assert case.coupon_at is not None


@pytest.mark.asyncio
async def test_t14_coupon_goes_to_the_case_of_its_own_phone(
    session_factory, make_manager
):
    """Ikkita case bor: eskisi yopilgan, yangisi ochiq. Kupon o'z nomeriga
    tegishli case'ga tushishi kerak — "oxirgi ochiq"ka emas."""
    await _seed_admin(session_factory)
    manager = make_manager()

    eski = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    async with session_factory() as session:
        case = await session.get(Case, eski.case.id)
        case.status = CaseStatus.REJECTED  # yopildi
        await session.commit()

    yangi = await manager.handle_phone_detected(
        ADMIN_ID, TG_ID, None, None, OTHER_PHONE
    )

    await manager.handle_coupon_detected(TG_ID, "123456", phone=OTHER_PHONE)

    async with session_factory() as session:
        eski_db = await session.get(Case, eski.case.id)
        yangi_db = await session.get(Case, yangi.case.id)
    assert yangi_db.coupon == "123456"
    assert eski_db.coupon is None


@pytest.mark.asyncio
async def test_t14_coupon_for_a_closed_case_is_ignored(session_factory, make_manager):
    """Nomer aniq ko'rsatilgan, lekin unga tegishli case yopilgan — kuponni
    boshqa joyga yozib qo'yish xato dalil yaratardi."""
    await _seed_admin(session_factory)
    manager = make_manager()
    eski = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    async with session_factory() as session:
        case = await session.get(Case, eski.case.id)
        case.status = CaseStatus.REJECTED
        await session.commit()

    await manager.handle_coupon_detected(TG_ID, "123456", phone=PHONE)

    async with session_factory() as session:
        case = await session.get(Case, eski.case.id)
    assert case.coupon is None


@pytest.mark.asyncio
async def test_t14_coupon_without_phone_still_uses_latest_open_case(
    session_factory, make_manager
):
    """Regressiya: nomersiz kupon (alohida xabarda) avvalgidek oxirgi ochiq
    case'ga bog'lanadi — bu to'g'ri xatti-harakat."""
    await _seed_admin(session_factory)
    manager = make_manager()
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    await manager.handle_coupon_detected(TG_ID, "123456")

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
    assert case.coupon == "123456"


@pytest.mark.asyncio
async def test_coupon_without_open_case_ignored(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()

    await manager.handle_coupon_detected(TG_ID, "123456")  # user ham yo'q — jim

    async with session_factory() as session:
        cases = (await session.execute(select(Case))).scalars().all()
    assert cases == []


@pytest.mark.asyncio
async def test_same_phone_while_open_no_new_case(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()
    first = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    second = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    assert second.customer_text is None
    assert second.case.id == first.case.id
    async with session_factory() as session:
        cases = (await session.execute(select(Case))).scalars().all()
    assert len(cases) == 1


@pytest.mark.asyncio
async def test_different_phone_while_open_alerts_admin(session_factory, make_manager):
    await _seed_admin(session_factory)
    alerts: list[str] = []

    async def capture_alert(message: str, important: bool = True) -> None:
        alerts.append(message)

    manager = make_manager(alert_sink=capture_alert)
    first = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    second = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, OTHER_PHONE)

    # Mijozga DUPLICATE_ACTIVE matni ketadi (avval tizim jim turardi —
    # foydalanuvchi qaroriga ko'ra yoqildi, `test_legacy_templates_live.py`).
    assert second.customer_text
    assert second.case.id == first.case.id  # yangi case ochilmaydi
    assert len(alerts) == 1
    assert OTHER_PHONE in alerts[0]


@pytest.mark.asyncio
async def test_passed_phone_same_user_gets_template(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
        case.status = CaseStatus.PASSED
        await session.commit()

    again = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    assert again.customer_text is not None  # ALREADY_CONFIRMED shabloni
    async with session_factory() as session:
        cases = (await session.execute(select(Case))).scalars().all()
    assert len(cases) == 1  # yangi case ochilmadi


@pytest.mark.asyncio
async def test_v1_confirmed_also_counts_as_passed(session_factory, make_manager):
    """Eski bazadagi CONFIRMED nomerlar himoyasi v2'da yo'qolmasligi kerak."""
    await _seed_admin(session_factory)
    manager = make_manager()
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
        case.status = CaseStatus.CONFIRMED
        await session.commit()

    again = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    assert again.customer_text is not None


@pytest.mark.asyncio
async def test_passed_phone_other_account_suspicious(session_factory, make_manager):
    await _seed_admin(session_factory)
    suspicious: list[tuple] = []

    async def capture(message, case_id, tg_user_id, tg_username):
        suspicious.append((message, case_id, tg_user_id))

    manager = make_manager(suspicious_alert_sink=capture)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
        case.status = CaseStatus.PASSED
        await session.commit()

    other = await manager.handle_phone_detected(ADMIN_ID, 222, "boshqa", None, PHONE)

    assert other.customer_text is None  # mijozga jim
    assert other.case.status == CaseStatus.SUSPICIOUS_HOLD
    assert len(suspicious) == 1
    async with session_factory() as session:
        user = (
            (await session.execute(select(User).where(User.tg_user_id == 222)))
            .scalars()
            .first()
        )
    assert user.is_safe is False


@pytest.mark.asyncio
async def test_open_phone_other_account_suspicious(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()
    await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    other = await manager.handle_phone_detected(ADMIN_ID, 222, None, None, PHONE)

    assert other.case.status == CaseStatus.SUSPICIOUS_HOLD


@pytest.mark.asyncio
async def test_blocked_user_silent(session_factory, make_manager):
    await _seed_admin(session_factory)
    manager = make_manager()
    async with session_factory() as session:
        session.add(User(tg_user_id=TG_ID, is_blocked=True))
        await session.commit()

    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    assert outcome.customer_text is None
    assert outcome.case is None
    async with session_factory() as session:
        cases = (await session.execute(select(Case))).scalars().all()
    assert cases == []
