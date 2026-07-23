import asyncio

from sqlalchemy import select

from core import texts
from core.enums import CaseStatus
from core.models import Bot, Case, User
from teleton_service.mock_bot import MockVerificationBot


async def _latest_case(session_factory, tg_user_id: int) -> Case:
    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        ).scalars().first()
        return (
            await session.execute(
                select(Case).where(Case.user_id == user.id).order_by(Case.id.desc())
            )
        ).scalars().first()


async def _case_count(session_factory, tg_user_id: int) -> int:
    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        ).scalars().first()
        rows = (
            await session.execute(select(Case).where(Case.user_id == user.id))
        ).scalars().all()
        return len(rows)


async def _bot_busy_count(session_factory) -> int:
    async with session_factory() as session:
        rows = (await session.execute(select(Bot).where(Bot.is_busy.is_(True)))).scalars().all()
        return len(rows)


async def test_full_success_flow(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()

    outcome = await cm.handle_phone_detected(111, "user1", "User One", "998901234567")
    assert outcome.customer_text == texts.COUPON_REQUEST

    case = await _latest_case(session_factory, 111)
    assert case.status == CaseStatus.AWAITING_COUPON
    assert case.bot_id is not None

    outcome2 = await cm.handle_coupon_received(111, "111111")
    assert outcome2.customer_text == texts.CONFIRMED

    case = await _latest_case(session_factory, 111)
    assert case.status == CaseStatus.CONFIRMED
    assert case.confirmed_at is not None
    assert await _bot_busy_count(session_factory) == 0


async def test_rejected_flow(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(222, "user2", "User Two", "998901234567")
    outcome = await cm.handle_coupon_received(222, "000000")

    assert outcome.customer_text == texts.REJECTED
    case = await _latest_case(session_factory, 222)
    assert case.status == CaseStatus.REJECTED
    assert await _bot_busy_count(session_factory) == 0


async def test_expired_same_phone_resend_retries_same_case(seed_bots, make_case_manager, session_factory):
    # TZ 2.1 (Q57) — MVP-3: EXPIRED'dan keyin AYNAN O'SHA nomer qaytadan
    # kelsa, bu YANGI case emas, balki eskisining qayta-urinishi.
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(333, "user3", "User Three", "998901234567")
    outcome = await cm.handle_coupon_received(333, "222222")
    assert outcome.customer_text == texts.EXPIRED_RETRY

    case = await _latest_case(session_factory, 333)
    assert case.status == CaseStatus.EXPIRED
    assert case.expired_attempts == 1
    assert await _bot_busy_count(session_factory) == 0  # bot darhol bo'shadi (2.1/3.5)

    outcome2 = await cm.handle_phone_detected(333, "user3", "User Three", "998901234567")
    assert outcome2.customer_text == texts.COUPON_REQUEST
    assert await _case_count(session_factory, 333) == 1  # YANGI case OCHILMAYDI

    retried_case = await _latest_case(session_factory, 333)
    assert retried_case.id == case.id
    assert retried_case.status == CaseStatus.AWAITING_COUPON


async def test_expired_different_phone_treated_as_duplicate_active(
    seed_bots, make_case_manager, session_factory
):
    # TZ EXPIRED'da aniq javob bermagan holat — eski case hali "hal
    # bo'lmagan" deb hisoblanadi, farqli nomer 2.3 kabi ushlanadi.
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()

    await cm.handle_phone_detected(334, "user3b", "User 3B", "998901234567")
    await cm.handle_coupon_received(334, "222222")  # EXPIRED

    outcome = await cm.handle_phone_detected(334, "user3b", "User 3B", "998907654321")
    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _case_count(session_factory, 334) == 2


async def test_expired_five_times_escalates_to_needs_admin(seed_bots, make_case_manager, session_factory):
    # TZ 2.1 (Q59) — 5 marta ketma-ket EXPIRED bo'lsa NEEDS_ADMIN.
    # Har urinishda BOSHQA kupon ishlatiladi — bir xilini qaytarsak Q58
    # (dublikat-kupon) uni botga yubormay bloklaydi, bu alohida testda tekshiriladi.
    expired_coupons = ["222222", "222223", "222224", "222225", "222226"]

    await seed_bots(["bot1"])
    cm = make_case_manager(
        bot_client=MockVerificationBot(
            extra_outcomes={c: CaseStatus.EXPIRED for c in expired_coupons}
        )
    )

    await cm.handle_phone_detected(335, "user3c", "User 3C", "998901234567")
    for i, coupon in enumerate(expired_coupons):
        outcome = await cm.handle_coupon_received(335, coupon)
        assert outcome.customer_text == texts.EXPIRED_RETRY
        if i < 4:
            await cm.handle_phone_detected(335, "user3c", "User 3C", "998901234567")

    case = await _latest_case(session_factory, 335)
    assert case.status == CaseStatus.NEEDS_ADMIN
    assert case.expired_attempts == 5
    assert await _case_count(session_factory, 335) == 1  # bir xil case davom etdi


async def test_duplicate_expired_coupon_resend_is_blocked(seed_bots, make_case_manager, session_factory):
    # TZ 2.1 (Q58) — eskisi bilan bir xil (allaqachon EXPIRED bo'lgan) kupon
    # qayta yuborilsa, botga yuborilmaydi.
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(336, "user3d", "User 3D", "998901234567")
    await cm.handle_coupon_received(336, "222222")  # EXPIRED, expired_attempts=1
    await cm.handle_phone_detected(336, "user3d", "User 3D", "998901234567")  # retry

    outcome = await cm.handle_coupon_received(336, "222222")  # xuddi shu kupon qayta
    assert outcome.customer_text == texts.DUPLICATE_COUPON

    case = await _latest_case(session_factory, 336)
    assert case.status == CaseStatus.AWAITING_COUPON  # hali botga yuborilmadi
    assert case.expired_attempts == 1  # oshmagan


async def test_duplicate_active_case_not_sent_to_bot(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1", "bot2"])
    alerts = []

    async def capture_alert(message: str, important: bool = True) -> None:
        alerts.append(message)

    cm = make_case_manager(alert_sink=capture_alert)

    await cm.handle_phone_detected(444, "user4", "User Four", "998901234567")
    outcome = await cm.handle_phone_detected(444, "user4", "User Four", "998907654321")

    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _bot_busy_count(session_factory) == 1  # ikkinchi nomer botga yuborilmadi
    assert any("ikkinchi nomer" in msg for msg in alerts)

    new_case = await _latest_case(session_factory, 444)
    assert new_case.status == CaseStatus.DUPLICATE_ACTIVE
    assert new_case.bot_id is None


async def test_already_confirmed_number_not_sent_to_bot(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(555, "user5", "User Five", "998901234567")
    await cm.handle_coupon_received(555, "111111")  # CONFIRMED bo'ladi

    outcome = await cm.handle_phone_detected(555, "user5", "User Five", "998901234567")
    assert outcome.customer_text == texts.ALREADY_CONFIRMED
    assert await _bot_busy_count(session_factory) == 0
    assert await _case_count(session_factory, 555) == 1  # yangi case ochilmadi


async def test_queued_case_dispatched_when_bot_frees_up(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    notifications = []

    async def capture_notify(tg_user_id: int, text: str) -> None:
        notifications.append((tg_user_id, text))

    cm = make_case_manager(notify_customer=capture_notify)

    outcome1 = await cm.handle_phone_detected(661, "user6", "User Six", "998901111111")
    assert outcome1.customer_text == texts.COUPON_REQUEST

    outcome2 = await cm.handle_phone_detected(662, "user7", "User Seven", "998902222222")
    assert outcome2.customer_text is None  # navbatga tushdi, bo'sh bot yo'q

    case2 = await _latest_case(session_factory, 662)
    assert case2.status == CaseStatus.NUMBER_RECEIVED

    await cm.handle_coupon_received(661, "111111")  # CONFIRMED, bot bo'shaydi

    assert notifications == [(662, texts.COUPON_REQUEST)]
    case2 = await _latest_case(session_factory, 662)
    assert case2.status == CaseStatus.AWAITING_COUPON
    assert case2.bot_id is not None


async def test_customer_timeout_frees_bot_and_late_coupon_gets_retry_text(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    cm = make_case_manager(customer_timeout_seconds=0.05)

    await cm.handle_phone_detected(771, "user8", "User Eight", "998901234567")
    await asyncio.sleep(0.2)

    case = await _latest_case(session_factory, 771)
    assert case.status == CaseStatus.CUSTOMER_TIMEOUT
    assert await _bot_busy_count(session_factory) == 0

    outcome = await cm.handle_coupon_received(771, "111111")
    assert outcome.customer_text == texts.EXPIRED_RETRY


async def test_coupon_without_active_case_is_ignored(make_case_manager):
    cm = make_case_manager()
    outcome = await cm.handle_coupon_received(999, "111111")
    assert outcome is None
