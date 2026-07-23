"""MVP-3: EXPIRED-qayta-urinish sikli asosiy testlari `test_case_state_machine.py`da.
Bu fayl qolgan MVP-3 xususiyatlarini qamrab oladi: shubhali-holat aniqlash
va qayta ishga tushirish (5.2), bloklangan foydalanuvchi (5.2 oqibati),
rasm-o'rniga-kupon (5.1), va tekshiruv bot timeout/retry (12-bo'lim)."""

from sqlalchemy import select

from core import texts
from core.enums import CaseStatus
from core.models import Case, User
from teleton_service.mock_bot import MockVerificationBot
from tests.test_case_state_machine import _bot_busy_count, _case_count, _latest_case


# --------------------------------------------------------------------------- #
# Shubhali holat — bir nomer turli akkauntdan (TZ 5.2)
# --------------------------------------------------------------------------- #


async def test_suspicious_cross_account_holds_and_does_not_dispatch(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1", "bot2"])
    suspicious_alerts = []

    async def capture_suspicious(message, case_id, tg_user_id, tg_username):
        suspicious_alerts.append((message, case_id, tg_user_id, tg_username))

    cm = make_case_manager(suspicious_alert_sink=capture_suspicious)

    await cm.handle_phone_detected(501, "userA", "User A", "998901234567")
    outcome = await cm.handle_phone_detected(502, "userB", "User B", "998901234567")

    assert outcome.customer_text is None

    case = await _latest_case(session_factory, 502)
    assert case.status == CaseStatus.SUSPICIOUS_HOLD
    assert case.bot_id is None
    assert suspicious_alerts and suspicious_alerts[0][2] == 502

    async with session_factory() as session:
        user_b = (
            await session.execute(select(User).where(User.tg_user_id == 502))
        ).scalars().first()
        assert user_b.is_safe is False


async def test_resume_suspicious_case_dispatches_after_marked_safe(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()

    await cm.handle_phone_detected(511, "userC", "User C", "998901234567")
    await cm.handle_phone_detected(512, "userD", "User D", "998901234567")  # SUSPICIOUS_HOLD

    case = await _latest_case(session_factory, 512)
    assert case.status == CaseStatus.SUSPICIOUS_HOLD

    async with session_factory() as session:
        user_d = await session.get(User, case.user_id)
        user_d.is_safe = True
        await session.commit()

        refreshed_case = await session.get(Case, case.id)
        outcome = await cm.resume_suspicious_case(session, refreshed_case)
        assert outcome.customer_text == texts.COUPON_REQUEST

    final_case = await _latest_case(session_factory, 512)
    assert final_case.status == CaseStatus.AWAITING_COUPON
    assert final_case.bot_id is not None


# --------------------------------------------------------------------------- #
# Bloklangan foydalanuvchi — jim e'tiborsiz qoldiriladi (5.2 oqibati)
# --------------------------------------------------------------------------- #


async def test_blocked_user_is_silently_ignored(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(520, "userE", "User E", "998901234567")

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == 520))
        ).scalars().first()
        user.is_blocked = True
        await session.commit()

    outcome = await cm.handle_phone_detected(520, "userE", "User E", "998907654321")
    assert outcome.customer_text is None
    assert await _case_count(session_factory, 520) == 1  # yangi case ochilmadi

    outcome2 = await cm.handle_coupon_received(520, "111111")
    assert outcome2 is None


# --------------------------------------------------------------------------- #
# Rasm o'rniga kupon (TZ 5.1)
# --------------------------------------------------------------------------- #


async def test_image_instead_of_coupon_warns_admin_and_keeps_awaiting(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    image_warnings = []

    async def capture_image(message, tg_user_id, tg_username):
        image_warnings.append((message, tg_user_id, tg_username))

    cm = make_case_manager(image_warning_sink=capture_image)
    await cm.handle_phone_detected(530, "userF", "User F", "998901234567")

    outcome = await cm.handle_non_text_coupon_input(530, "userF", "User F")
    assert outcome.customer_text == texts.IMAGE_INSTEAD_OF_TEXT
    assert image_warnings and image_warnings[0][1] == 530

    case = await _latest_case(session_factory, 530)
    assert case.status == CaseStatus.AWAITING_COUPON  # holat o'zgarmadi


async def test_image_input_ignored_when_no_coupon_expected(seed_bots, make_case_manager):
    await seed_bots(["bot1"])
    cm = make_case_manager()
    # Hech qanday case yo'q holatda rasm kelsa — oddiy suhbat, hech narsa qilinmaydi.
    outcome = await cm.handle_non_text_coupon_input(9999, "nobody", "Nobody")
    assert outcome is None


# --------------------------------------------------------------------------- #
# Tekshiruv bot javob bermasa — timeout/retry (TZ 12-bo'lim)
# --------------------------------------------------------------------------- #


async def test_request_coupon_timeout_after_retries_sets_case_timeout(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    alerts = []

    async def capture_alert(message, important=True):
        alerts.append((message, important))

    bot_client = MockVerificationBot(unresponsive_phones={"+998901234567"})
    cm = make_case_manager(
        bot_client=bot_client,
        alert_sink=capture_alert,
        bot_response_max_retries=2,
        bot_response_backoff_seconds=0,
    )

    outcome = await cm.handle_phone_detected(540, "userG", "User G", "998901234567")
    assert outcome.customer_text is None

    case = await _latest_case(session_factory, 540)
    assert case.status == CaseStatus.TIMEOUT
    assert await _bot_busy_count(session_factory) == 0
    assert any("TIMEOUT" in m and important for m, important in alerts)


async def test_check_coupon_timeout_after_retries_sets_case_timeout(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    bot_client = MockVerificationBot(unresponsive_coupons={"999999"})
    cm = make_case_manager(
        bot_client=bot_client, bot_response_max_retries=2, bot_response_backoff_seconds=0
    )

    await cm.handle_phone_detected(541, "userH", "User H", "998901234567")
    outcome = await cm.handle_coupon_received(541, "999999")
    assert outcome.customer_text is None

    case = await _latest_case(session_factory, 541)
    assert case.status == CaseStatus.TIMEOUT
    assert await _bot_busy_count(session_factory) == 0
