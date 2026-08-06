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
    original = await _latest_case(session_factory, 334)

    outcome = await cm.handle_phone_detected(334, "user3b", "User 3B", "998907654321")
    assert outcome.customer_text == texts.DUPLICATE_ACTIVE

    # Audit K-1 — YANGI, bo'sh case ochilmaydi: MAVJUD (band) case joyida
    # DUPLICATE_ACTIVE'ga o'tkaziladi, asl nomer o'zgarmaydi.
    assert await _case_count(session_factory, 334) == 1
    held = await _latest_case(session_factory, 334)
    assert held.id == original.id
    assert held.status == CaseStatus.DUPLICATE_ACTIVE
    assert held.phone == "998901234567"  # asl (band) nomer, yangisi emas


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
    original = await _latest_case(session_factory, 444)
    outcome = await cm.handle_phone_detected(444, "user4", "User Four", "998907654321")

    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _bot_busy_count(session_factory) == 1  # ikkinchi nomer botga yuborilmadi
    assert any("ikkinchi nomer" in msg for msg in alerts)

    # Audit K-1/O-5 — yangi, bo'sh case ochilmaydi: MAVJUD (band) case
    # joyida DUPLICATE_ACTIVE'ga o'tkaziladi, bot biriktirilgani saqlanadi.
    assert await _case_count(session_factory, 444) == 1
    held_case = await _latest_case(session_factory, 444)
    assert held_case.id == original.id
    assert held_case.status == CaseStatus.DUPLICATE_ACTIVE
    assert held_case.bot_id is not None


async def test_third_message_still_held_not_dispatched_to_new_bot(
    seed_bots, make_case_manager, session_factory
):
    """Audit K-1 — asosiy regressiya: mijoz bir xil (yoki turli) nomerni
    ketma-ket 3+ marta yuborsa, tizim HECH QACHON yangi bot/case ochmasligi
    kerak (TZ 2.3 — "avtomatik hech narsa hal qilinmaydi"). Tuzatishdan
    oldin uchinchi xabar "yangi murojaat" deb noto'g'ri qabul qilinib, YANGI
    bot band qilinardi."""
    await seed_bots(["bot1", "bot2", "bot3"])
    cm = make_case_manager()

    await cm.handle_phone_detected(445, "user5", "User Five", "998901234567")
    original = await _latest_case(session_factory, 445)

    await cm.handle_phone_detected(445, "user5", "User Five", "998907654321")
    await cm.handle_phone_detected(445, "user5", "User Five", "998907654322")

    # Faqat BITTA case, faqat BITTA bot band — ikkinchi/uchinchi bot HECH
    # QACHON ishga tushmadi.
    assert await _case_count(session_factory, 445) == 1
    assert await _bot_busy_count(session_factory) == 1
    case = await _latest_case(session_factory, 445)
    assert case.id == original.id
    assert case.status == CaseStatus.DUPLICATE_ACTIVE


async def test_new_number_while_needs_admin_stays_held(seed_bots, make_case_manager, session_factory):
    """Audit K-1 — 5x EXPIRED'dan keyin NEEDS_ADMIN'ga o'tgan case ustiga
    mijoz yana nomer yuborsa, avtomatik yangi dispatch bo'lmasligi kerak."""
    expired_coupons = ["222222", "222223", "222224", "222225", "222226"]
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager(
        bot_client=MockVerificationBot(extra_outcomes={c: CaseStatus.EXPIRED for c in expired_coupons})
    )

    await cm.handle_phone_detected(446, "user6", "User Six", "998901234567")
    for i, coupon in enumerate(expired_coupons):
        await cm.handle_coupon_received(446, coupon)
        if i < 4:
            await cm.handle_phone_detected(446, "user6", "User Six", "998901234567")

    case = await _latest_case(session_factory, 446)
    assert case.status == CaseStatus.NEEDS_ADMIN

    outcome = await cm.handle_phone_detected(446, "user6", "User Six", "998909999999")
    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _case_count(session_factory, 446) == 1  # yangi case ochilmadi
    held = await _latest_case(session_factory, 446)
    assert held.id == case.id
    assert held.status == CaseStatus.NEEDS_ADMIN  # status TEGILMAYDI (o'z oqimi bor)


async def test_new_number_while_bot_timeout_is_held(seed_bots, make_case_manager, session_factory):
    """Audit K-1 — bot javob bermay TIMEOUT bo'lgan case ustiga mijoz yana
    nomer yuborsa, avval bu holat umuman tekshirilmasdi (yangi bot ochilib
    ketardi)."""
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager(
        bot_client=MockVerificationBot(unresponsive_coupons={"999000"}),
        bot_response_max_retries=1,
    )

    await cm.handle_phone_detected(447, "user7", "User Seven", "998901234567")
    await cm.handle_coupon_received(447, "999000")
    case = await _latest_case(session_factory, 447)
    assert case.status == CaseStatus.TIMEOUT

    outcome = await cm.handle_phone_detected(447, "user7", "User Seven", "998908888888")
    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _case_count(session_factory, 447) == 1
    held = await _latest_case(session_factory, 447)
    assert held.id == case.id
    assert held.status == CaseStatus.TIMEOUT  # status TEGILMAYDI


async def test_customer_timeout_same_phone_restarts_process(
    seed_bots, make_case_manager, session_factory
):
    """TZ 2.2 — mijoz 5 daqiqadan keyin AYNAN O'SHA nomerni qaytadan
    yuborsa, jarayon boshidan boshlanadi (yangi bot, lekin case_id
    o'zgarmaydi)."""
    await seed_bots(["bot1"])
    cm = make_case_manager(customer_timeout_seconds=0.05)

    await cm.handle_phone_detected(448, "user8", "User Eight", "998901234567")
    await asyncio.sleep(0.2)
    case = await _latest_case(session_factory, 448)
    assert case.status == CaseStatus.CUSTOMER_TIMEOUT

    outcome = await cm.handle_phone_detected(448, "user8", "User Eight", "998901234567")
    assert outcome.customer_text == texts.COUPON_REQUEST
    assert await _case_count(session_factory, 448) == 1

    retried = await _latest_case(session_factory, 448)
    assert retried.id == case.id
    assert retried.status == CaseStatus.AWAITING_COUPON


async def test_customer_timeout_different_phone_is_held(seed_bots, make_case_manager, session_factory):
    """Audit K-1 — mijoz timeoutdan keyin BOSHQA nomer yuborsa, avval bu
    holat umuman tekshirilmasdi (yangi bot/case ochilib ketardi)."""
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager(customer_timeout_seconds=0.05)

    await cm.handle_phone_detected(449, "user9", "User Nine", "998901234567")
    await asyncio.sleep(0.2)
    case = await _latest_case(session_factory, 449)
    assert case.status == CaseStatus.CUSTOMER_TIMEOUT

    outcome = await cm.handle_phone_detected(449, "user9", "User Nine", "998907777777")
    assert outcome.customer_text == texts.DUPLICATE_ACTIVE
    assert await _case_count(session_factory, 449) == 1
    held = await _latest_case(session_factory, 449)
    assert held.id == case.id
    assert held.status == CaseStatus.DUPLICATE_ACTIVE


async def test_already_confirmed_number_not_sent_to_bot(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(555, "user5", "User Five", "998901234567")
    await cm.handle_coupon_received(555, "111111")  # CONFIRMED bo'ladi

    outcome = await cm.handle_phone_detected(555, "user5", "User Five", "998901234567")
    assert outcome.customer_text == texts.ALREADY_CONFIRMED
    assert await _bot_busy_count(session_factory) == 0
    assert await _case_count(session_factory, 555) == 1  # yangi case ochilmadi


async def test_confirmed_number_from_different_account_is_suspicious_not_silent(
    seed_bots, make_case_manager, session_factory
):
    """Audit O-1 (TZ 5.2) — agar tasdiqlangan nomerni BOSHQA Telegram
    akkaunt yuborsa, bu oddiy "allaqachon tasdiqlangan" javobidan ko'ra
    kuchliroq firibgarlik signali — jim javob emas, shubhali holat
    sifatida ushlanishi va adminga alert borishi kerak."""
    await seed_bots(["bot1", "bot2"])
    suspicious_alerts = []

    async def capture_suspicious(message, case_id, tg_user_id, tg_username):
        suspicious_alerts.append((case_id, tg_user_id))

    cm = make_case_manager(suspicious_alert_sink=capture_suspicious)

    await cm.handle_phone_detected(950, "ownerA", "Owner A", "998909990000")
    await cm.handle_coupon_received(950, "111111")  # CONFIRMED, user 950 egalik qiladi

    outcome = await cm.handle_phone_detected(951, "impostorB", "Impostor B", "998909990000")

    assert outcome.customer_text is None  # ALREADY_CONFIRMED emas, jim (shubha kabi)
    assert suspicious_alerts and suspicious_alerts[0][1] == 951

    new_case = await _latest_case(session_factory, 951)
    assert new_case.status == CaseStatus.SUSPICIOUS_HOLD


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


async def test_customer_timeout_uses_live_db_setting_when_not_explicit(
    seed_bots, make_case_manager, session_factory
):
    """Audit J-9 (TZ 2.2) — timeout qiymati konstruktorda ANIQ berilmasa
    (`None`), har safar timer boshlanganda BAZADAN o'qilishi kerak — shu
    orqali Adminbot orqali o'zgartirish qayta ishga tushirmasdan ta'sir
    qiladi."""
    from core.logic.settings_store import set_customer_timeout_seconds

    await seed_bots(["bot1"])
    async with session_factory() as session:
        await set_customer_timeout_seconds(session, 0.05)

    # `customer_timeout_seconds=None` — conftest'ning standart 9999'ini
    # ANIQ ravishda bekor qiladi, dinamik (bazadan o'qish) yo'lni yoqadi.
    cm = make_case_manager(customer_timeout_seconds=None)

    await cm.handle_phone_detected(891, "u", "U", "998901234568")
    await asyncio.sleep(0.2)

    case = await _latest_case(session_factory, 891)
    assert case.status == CaseStatus.CUSTOMER_TIMEOUT


async def test_relay_log_records_every_bot_exchange(seed_bots, make_case_manager, session_factory):
    """Audit J-7 (TZ 11.5) — `relay_log` avval umuman mavjud emas edi.
    Endi nomer/kupon yuborilganda VA bot javob berganda, ikkalasi ham
    yoziladi (natijadan qat'i nazar)."""
    from core.logic.relay_log import relay_log_for_case
    from core.models import RelayDirection

    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(890, "u", "U", "998901234567")
    case = await _latest_case(session_factory, 890)
    await cm.handle_coupon_received(890, "111111")  # CONFIRMED

    async with session_factory() as session:
        entries = await relay_log_for_case(session, case.id)

    directions = [(e.direction, e.payload) for e in entries]
    assert (RelayDirection.TO_BOT, "+998901234567") in directions
    assert (RelayDirection.FROM_BOT, "Kupon raqamini yuboring.") in directions
    assert (RelayDirection.TO_BOT, "111111") in directions
    assert any(d == RelayDirection.FROM_BOT and "Muvaffaqiyatli" in p for d, p in directions)
