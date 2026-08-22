"""Tugmali interfeys ortidagi yangi admin amallari — TZ 3.3, 5.2, 9.3, 9.5, 11.1.

Bular avval TZ'da talab qilingan, lekin hech qachon qurilmagan funksiyalar:
botni yoqish/o'chirish, format o'zgartirish, qo'lda tasdiqlash/rad etish/
qayta uzatish, blokdan chiqarish, mijozga izoh.
"""

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.bot_pool import (
    PHONE_FORMATS,
    add_bot,
    get_bot,
    request_bot_force_release,
    set_bot_active,
    set_bot_phone_format,
)
from core.logic.case_admin import (
    InvalidCaseStateError,
    assign_customer,
    get_case_bundle,
    list_cases_by_statuses,
    manual_confirm,
    manual_reject,
    request_redispatch,
    set_user_blocked,
    set_user_note,
    set_user_safe,
)
from core.models import Bot, Case, User
from tests.test_case_state_machine import _bot_busy_count, _latest_case


# --------------------------------------------------------------------------- #
# Botni yoqish / o'chirish (TZ 3.3) — o'chirilgan bot tanlanmasligi kerak
# --------------------------------------------------------------------------- #


async def test_set_bot_active_toggles_flag(session_factory, seed_bots):
    await seed_bots(["b1"])
    async with session_factory() as session:
        bot = (await session.execute(select(Bot))).scalars().first()

        off = await set_bot_active(session, bot.id, False)
        assert off.is_active is False

        on = await set_bot_active(session, bot.id, True)
        assert on.is_active is True


async def test_deactivated_bot_is_not_dispatched_to(seed_bots, make_case_manager, session_factory):
    # TZ 3.3 — "vaqtincha to'xtatish" haqiqatan ishlashi kerak: o'chirilgan bot
    # pool tanlovidan chiqib ketadi, case navbatga tushadi.
    await seed_bots(["only_bot"])
    async with session_factory() as session:
        bot = (await session.execute(select(Bot))).scalars().first()
        await set_bot_active(session, bot.id, False)

    cm = make_case_manager()
    outcome = await cm.handle_phone_detected(2001, "u", "U", "998901234567")

    assert outcome.customer_text is None  # bot topilmadi -> navbat
    case = await _latest_case(session_factory, 2001)
    assert case.status == CaseStatus.NUMBER_RECEIVED
    assert case.bot_id is None


async def test_set_bot_active_returns_none_for_missing_bot(session_factory):
    async with session_factory() as session:
        assert await set_bot_active(session, 999, False) is None


async def test_request_bot_force_release_sets_flag_for_teleton_to_pick_up(
    seed_bots, make_case_manager, session_factory
):
    """Audit J-4 (TZ 12) — Adminbot "Majburan bo'shatish" faqat bayroq
    qo'yadi (haqiqiy bo'shatishni jarayon-ichidagi Teleton bajaradi,
    `admin_redispatch_requested` bilan bir xil naqsh). Bayroq qo'yilgach,
    Teletonning HAQIQIY `BotPoolManager.force_release`si chaqirilsa,
    navbatdagi case darhol shu botga tayinlanishi kerak."""
    await seed_bots(["only_bot"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2800, "u1", "U1", "998900000010")  # only_bot band bo'ladi
    outcome_queued = await cm.handle_phone_detected(2801, "u2", "U2", "998900000011")
    assert outcome_queued.customer_text is None  # navbatga tushdi

    async with session_factory() as session:
        bot = (await session.execute(select(Bot))).scalars().first()

        updated = await request_bot_force_release(session, bot.id)
        assert updated.force_release_requested is True
        assert updated.is_busy is True  # o'zi hali bo'shatilmagan — faqat SO'RALGAN

    # Teleton fon vazifasi shu tarzda ishlaydi (_force_release_watcher):
    async with session_factory() as session:
        bot = await session.get(Bot, bot.id)
        bot.force_release_requested = False
        await session.commit()
        await cm.pool.force_release(session, bot.id)

    async with session_factory() as session:
        freed = await session.get(Bot, bot.id)
        assert freed.force_release_requested is False
        # Navbatdagi case shu botga darhol tayinlangan bo'lishi kerak.
        assert freed.is_busy is True
        case2 = await _latest_case(session_factory, 2801)
        assert case2.status == CaseStatus.AWAITING_COUPON
        assert case2.bot_id == bot.id


async def test_request_bot_force_release_returns_none_for_missing_bot(session_factory):
    async with session_factory() as session:
        assert await request_bot_force_release(session, 999) is None


# --------------------------------------------------------------------------- #
# Nomer formatini keyin o'zgartirish (TZ 9.5, Q53)
# --------------------------------------------------------------------------- #


async def test_set_bot_phone_format_updates_and_validates(session_factory):
    async with session_factory() as session:
        bot = await add_bot(session, "fmt_bot")
        assert bot.phone_format == PHONE_FORMATS[0]

        updated = await set_bot_phone_format(session, bot.id, "XXXXXXXXX")
        assert updated.phone_format == "XXXXXXXXX"

        with pytest.raises(ValueError):
            await set_bot_phone_format(session, bot.id, "noto'g'ri-format")


async def test_add_bot_rejects_invalid_phone_format(session_factory):
    """Audit K-2 — bot BIRINCHI marta qo'shilganda ham format tekshirilishi
    kerak, keyinroq o'zgartirilganda emas (aks holda noto'g'ri formatli bot
    birinchi mijozga tushganda kutilmagan xato bilan abadiy "band" bo'lib
    qolardi)."""
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await add_bot(session, "bad_fmt_bot", "998-XX-XXX-XX-XX")

        result = (await session.execute(select(Bot).where(Bot.username == "bad_fmt_bot"))).scalars().first()
        assert result is None  # yozilmagan


async def test_bad_bot_format_escalates_to_needs_admin_instead_of_hanging(
    session_factory, seed_bots, make_case_manager
):
    """Audit K-2 — mudofaa qatlami: agar (eski, tuzatishdan oldingi
    yozuvlar kabi) bazada ALLAQACHON noto'g'ri formatli bot bo'lsa,
    case_manager uni abadiy band qilib qo'ymasligi, aksincha NEEDS_ADMIN'ga
    o'tkazib botni bo'shatishi kerak."""
    await seed_bots(["ok_bot"])
    async with session_factory() as session:
        bot = (await session.execute(select(Bot))).scalars().first()
        # Tekshiruvni chetlab, to'g'ridan-to'g'ri bazaga noto'g'ri format yozamiz
        # (add_bot/set_bot_phone_format endi buni rad etadi — shuning uchun
        # "eski, migratsiyadan oldingi yozuv" holatini qo'lda simulyatsiya qilamiz).
        bot.phone_format = "noto'g'ri-format"
        await session.commit()

    cm = make_case_manager()
    outcome = await cm.handle_phone_detected(2600, "u", "U", "998901234567")

    assert outcome.customer_text is None  # mijozga jim (ichki xato, shablon yo'q)
    case = await _latest_case(session_factory, 2600)
    assert case.status == CaseStatus.NEEDS_ADMIN
    assert await _bot_busy_count(session_factory) == 0  # bot abadiy band bo'lib qolmadi


async def test_changed_format_is_used_when_talking_to_bot(seed_bots, make_case_manager, session_factory):
    """Format o'zgarishi haqiqatan botga uzatilgan nomerga ta'sir qiladi."""
    await seed_bots(["fbot"])
    async with session_factory() as session:
        bot = (await session.execute(select(Bot))).scalars().first()
        await set_bot_phone_format(session, bot.id, "XXXXXXXXX")

    seen: list[str] = []

    class _Recorder:
        async def request_coupon(self, bot, phone: str) -> str:
            seen.append(phone)
            return "ok"

        async def check_coupon(self, bot, coupon: str):
            return CaseStatus.CONFIRMED, "ok"

    cm = make_case_manager(bot_client=_Recorder())
    await cm.handle_phone_detected(2002, "u", "U", "998901234567")

    assert seen == ["901234567"]  # +998 prefiksisiz — yangi format


# --------------------------------------------------------------------------- #
# TZ 9.3 — qo'lda Tasdiqlash / Rad etish / Qayta uzatish
# --------------------------------------------------------------------------- #


async def test_manual_confirm_sets_confirmed_with_timestamp(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2100, "u", "U", "998901111111")
    case = await _latest_case(session_factory, 2100)

    async with session_factory() as session:
        # Audit K-3 — manual_confirm endi faqat MANUAL_RESOLVABLE_STATUSES
        # holatida ishlaydi; case hozir AWAITING_COUPON (haqiqiy tekshiruv
        # hali tugamagan), shuning uchun testda uni NEEDS_ADMIN'ga o'tkazamiz
        # ("bot noaniq javob berdi, admin qo'lda hal qiladi" stsenariysi).
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()

        updated = await manual_confirm(session, case.id)

    assert updated.status == CaseStatus.CONFIRMED
    assert updated.confirmed_at is not None


async def test_manual_reject_sets_rejected(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2101, "u", "U", "998902222222")
    case = await _latest_case(session_factory, 2101)

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()

        updated = await manual_reject(session, case.id)

    assert updated.status == CaseStatus.REJECTED


async def test_request_redispatch_queues_case_and_sets_flag(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2102, "u", "U", "998903333333")
    case = await _latest_case(session_factory, 2102)

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()

        updated = await request_redispatch(session, case.id)

    assert updated.status == CaseStatus.NUMBER_RECEIVED
    assert updated.bot_id is None
    assert updated.admin_redispatch_requested is True


async def test_manual_resolution_clears_redispatch_flag(seed_bots, make_case_manager, session_factory):
    """Qayta uzatish so'ralib, keyin (masalan Teleton qaytadan dispatch
    qilib, bot yana noaniq javob bergach) qo'lda hal qilinsa — bayroq
    qolmasligi kerak, aks holda Teleton allaqachon yopilgan case'ni
    dispatch qilardi."""
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2103, "u", "U", "998904444444")
    case = await _latest_case(session_factory, 2103)

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()
        await request_redispatch(session, case.id)

        # Qayta uzatishdan keyin case NUMBER_RECEIVED'da (bu holat endi
        # qo'lda hal qilinmaydi — Teleton avtomatik dispatch qiladi).
        # Keyinroq bot yana noaniq javob bergan deb faraz qilamiz.
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()

        updated = await manual_confirm(session, case.id)

    assert updated.admin_redispatch_requested is False


async def test_manual_actions_return_none_for_missing_case(session_factory):
    async with session_factory() as session:
        assert await manual_confirm(session, 999) is None
        assert await manual_reject(session, 999) is None
        assert await request_redispatch(session, 999) is None


# --------------------------------------------------------------------------- #
# Audit K-3 — case joriy holati mos kelmasa, amal rad etilishi kerak
# --------------------------------------------------------------------------- #


async def test_manual_actions_raise_for_active_case(seed_bots, make_case_manager, session_factory):
    """Hali AWAITING_COUPON (haqiqiy tekshiruv davom etayotgan) case ustida
    Tasdiqlash/Rad/Qayta-uzatish chaqirilsa — hech narsa o'zgarmasligi va
    aniq xato ko'tarilishi kerak (bu K-3'ning o'zi tuzatgan xato edi:
    avval istalgan case tekshiruvsiz "tasdiqlanardi")."""
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2110, "u", "U", "998900000001")
    case = await _latest_case(session_factory, 2110)

    async with session_factory() as session:
        with pytest.raises(InvalidCaseStateError):
            await manual_confirm(session, case.id)
        with pytest.raises(InvalidCaseStateError):
            await manual_reject(session, case.id)
        with pytest.raises(InvalidCaseStateError):
            await request_redispatch(session, case.id)

        unchanged = await session.get(Case, case.id)
        assert unchanged.status == CaseStatus.AWAITING_COUPON


async def test_manual_actions_raise_for_suspicious_hold(seed_bots, make_case_manager, session_factory):
    """SUSPICIOUS_HOLD o'zining alohida Xavfsiz/Bloklash oqimiga ega (TZ
    5.2) — generic Tasdiqlash/Rad tugmalari orqali chetlab o'tilmasligi
    kerak."""
    await seed_bots(["b1", "b2"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2111, "ua", "UA", "998900000002")
    await cm.handle_phone_detected(2112, "ub", "UB", "998900000002")

    async with session_factory() as session:
        susp = (
            await session.execute(select(Case).where(Case.status == CaseStatus.SUSPICIOUS_HOLD))
        ).scalars().first()
        assert susp is not None

        with pytest.raises(InvalidCaseStateError):
            await manual_confirm(session, susp.id)

        unchanged = await session.get(Case, susp.id)
        assert unchanged.status == CaseStatus.SUSPICIOUS_HOLD


# --------------------------------------------------------------------------- #
# Bloklash / blokdan chiqarish / izoh (TZ 5.2, 11.1)
# --------------------------------------------------------------------------- #


async def test_block_then_unblock_restores_access(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1", "b2"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2200, "u", "U", "998905555555")

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 2200))).scalars().first()
        await set_user_blocked(session, user.id, True)

    # Bloklangan holatda tizim jim (MVP-3 xatti-harakati).
    assert (await cm.handle_phone_detected(2200, "u", "U", "998906666666")).customer_text is None

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 2200))).scalars().first()
        unblocked = await set_user_blocked(session, user.id, False)
        assert unblocked.is_blocked is False
        # Blokdan chiqarilganda shubha bayrog'i ham tozalanadi.
        assert unblocked.is_safe is True


async def test_set_user_safe_and_note(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2201, "u", "U", "998907777777")

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 2201))).scalars().first()

        await set_user_safe(session, user.id, False)
        refreshed = await session.get(User, user.id)
        assert refreshed.is_safe is False

        noted = await set_user_note(session, user.id, "VIP mijoz, ehtiyot bo'ling")
        assert noted.note == "VIP mijoz, ehtiyot bo'ling"


async def test_user_helpers_return_none_for_missing_user(session_factory):
    async with session_factory() as session:
        assert await set_user_blocked(session, 999, True) is None
        assert await set_user_safe(session, 999, True) is None
        assert await set_user_note(session, 999, "x") is None


async def test_returned_objects_are_fully_loaded_after_update(
    seed_bots, make_case_manager, session_factory
):
    """Regressiya: `users.last_seen` / `cases.updated_at` ustunlarida
    `onupdate=func.now()` bor — UPDATE'dan keyin SQLAlchemy ularni "eskirgan"
    deb belgilaydi. Ochiq `refresh` bo'lmasa, qaytarilgan obyektdan shu
    ustunlarni o'qish implicit async IO'ga urinib `MissingGreenlet` bergan
    (Adminbotda har bir "Bloklash"/"Izoh" bosilishida kartochka yasashda
    xato chiqardi)."""
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2500, "u", "U", "998909333333")
    case = await _latest_case(session_factory, 2500)

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 2500))).scalars().first()

        blocked = await set_user_blocked(session, user.id, True)
        assert blocked.last_seen is not None  # eskirgan ustun o'qilishi kerak

        noted = await set_user_note(session, user.id, "izoh")
        assert noted.last_seen is not None

        safed = await set_user_safe(session, user.id, True)
        assert safed.last_seen is not None

        # Audit K-3 — manual_confirm/manual_reject/request_redispatch endi
        # faqat MANUAL_RESOLVABLE_STATUSES holatida ishlaydi; har chaqiruv
        # case'ni shu ro'yxatdan CHIQARIB yuboradi, shuning uchun har
        # birini sinashdan oldin case'ni qayta NEEDS_ADMIN'ga qaytaramiz.
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()
        confirmed = await manual_confirm(session, case.id)
        assert confirmed.updated_at is not None

        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()
        rejected = await manual_reject(session, case.id)
        assert rejected.updated_at is not None

        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()
        requeued = await request_redispatch(session, case.id)
        assert requeued.updated_at is not None


# --------------------------------------------------------------------------- #
# Kartochka/ro'yxat yordamchilari (UI uchun)
# --------------------------------------------------------------------------- #


async def test_get_case_bundle_returns_case_user_and_attempts(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2300, "bundleuser", "Bundle", "998908888888")
    await cm.handle_coupon_received(2300, "111111")
    case = await _latest_case(session_factory, 2300)

    async with session_factory() as session:
        bundle = await get_case_bundle(session, case.id)

    assert bundle is not None
    got_case, got_user, attempts = bundle
    assert got_case.id == case.id
    assert got_user.tg_username == "bundleuser"
    assert [a.coupon for a in attempts] == ["111111"]

    async with session_factory() as session:
        assert await get_case_bundle(session, 999) is None


# --------------------------------------------------------------------------- #
# Audit K-4 (TZ 11.0, Q51) — har admin faqat o'ziga biriktirilgan (yoki hali
# hech kimga biriktirilmagan) mijoz/case'larni ko'radi.
# --------------------------------------------------------------------------- #


async def test_assign_customer_and_visibility_scoping(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1", "b2", "b3"])  # uchala mijoz ham AWAITING_COUPON'gacha yetishi uchun
    cm = make_case_manager()
    await cm.handle_phone_detected(2700, "ownuser", "OwnUser", "998900111111")  # admin #10ga
    await cm.handle_phone_detected(2701, "otheruser", "OtherUser", "998900222222")  # admin #20ga
    await cm.handle_phone_detected(2702, "freeuser", "FreeUser", "998900333333")  # hech kimga

    async with session_factory() as session:
        u10 = (await session.execute(select(User).where(User.tg_user_id == 2700))).scalars().first()
        u20 = (await session.execute(select(User).where(User.tg_user_id == 2701))).scalars().first()

        assigned = await assign_customer(session, u10.id, 10)
        assert assigned.assigned_admin_id == 10
        await assign_customer(session, u20.id, 20)

        # Admin #10 — faqat o'zinikini va biriktirilmaganini ko'radi.
        visible = await list_cases_by_statuses(
            session,
            [CaseStatus.AWAITING_COUPON],
            viewer_admin_id=10,
            can_see_all=False,
        )
        visible_phones = {c.phone for c in visible}
        assert visible_phones == {"998900111111", "998900333333"}
        assert "998900222222" not in visible_phones

        # Owner/Rop (can_see_all=True) — hammasini ko'radi.
        everything = await list_cases_by_statuses(
            session, [CaseStatus.AWAITING_COUPON], can_see_all=True
        )
        assert len(everything) == 3


async def test_get_case_bundle_hides_other_admins_case(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2703, "u", "U", "998900444444")
    case = await _latest_case(session_factory, 2703)

    async with session_factory() as session:
        user = await session.get(User, case.user_id)
        await assign_customer(session, user.id, 30)

        # Boshqa admin (id=31) ko'ra olmaydi.
        hidden = await get_case_bundle(session, case.id, viewer_admin_id=31, can_see_all=False)
        assert hidden is None

        # O'zi (id=30) ko'radi.
        own = await get_case_bundle(session, case.id, viewer_admin_id=30, can_see_all=False)
        assert own is not None

        # Owner/Rop (can_see_all=True) har doim ko'radi.
        as_owner = await get_case_bundle(session, case.id, can_see_all=True)
        assert as_owner is not None


async def test_assign_customer_returns_none_for_missing_user(session_factory):
    async with session_factory() as session:
        assert await assign_customer(session, 999, 10) is None


async def test_list_cases_by_statuses_filters_and_orders_newest_first(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["b1", "b2"])
    cm = make_case_manager()

    await cm.handle_phone_detected(2400, "u1", "U1", "998909111111")
    await cm.handle_coupon_received(2400, "333333")  # REJECTED

    await cm.handle_phone_detected(2401, "u2", "U2", "998909222222")
    await cm.handle_coupon_received(2401, "111111")  # CONFIRMED

    async with session_factory() as session:
        rejected = await list_cases_by_statuses(session, [CaseStatus.REJECTED])
        assert [c.phone for c in rejected] == ["998909111111"]

        both = await list_cases_by_statuses(
            session, [CaseStatus.REJECTED, CaseStatus.CONFIRMED]
        )
        # id bo'yicha kamayish tartibida — eng yangisi birinchi
        assert [c.phone for c in both] == ["998909222222", "998909111111"]


# --------------------------------------------------------------------------- #
# Nazorat guruhidagi "/" buyruq menyusi — har admin faqat o'ziga ochiq
# buyruqlarni ko'rsin (foydalanuvchi so'rovi: guruhda ko'rinish rolga qarab)
# --------------------------------------------------------------------------- #


async def test_sync_group_command_menus_filters_by_role(session_factory, monkeypatch):
    import adminbot_service.bot as ab
    from core.logic.admins import ensure_admins_seeded, set_admin_role
    from core.logic.settings_store import set_group_chat_id
    from core.models import Admin, AdminRole

    monkeypatch.setattr(ab, "get_session", session_factory)

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        await set_group_chat_id(session, -100500)
        owner, kuzatuvchi = (
            await session.execute(select(Admin).order_by(Admin.id))
        ).scalars().all()
        await set_admin_role(session, kuzatuvchi.id, AdminRole.KUZATUVCHI)

    calls: list[tuple] = []

    class FakeBot:
        async def set_my_commands(self, commands, scope):
            calls.append(("set", scope.user_id, {c.command for c in commands}))

        async def delete_my_commands(self, scope):
            calls.append(("delete", scope.user_id, set()))

    await ab.sync_group_command_menus(FakeBot())

    by_user = {user_id: cmds for kind, user_id, cmds in calls if kind == "set"}
    assert "setrole" in by_user[111]  # Owner — hammasi
    assert "setrole" not in by_user[222]  # Kuzatuvchi — bunga yopiq
    assert "help" in by_user[222]  # Kuzatuvchi — ko'rish baribir ochiq


async def test_sync_group_command_menus_clears_menu_for_inactive_admin(
    session_factory, monkeypatch
):
    import adminbot_service.bot as ab
    from core.logic.admins import ensure_admins_seeded
    from core.logic.settings_store import set_group_chat_id
    from core.models import Admin

    monkeypatch.setattr(ab, "get_session", session_factory)

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        await set_group_chat_id(session, -100500)
        target = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 222))
        ).scalars().first()
        target.is_active = False
        await session.commit()

    calls: list[tuple] = []

    class FakeBot:
        async def set_my_commands(self, commands, scope):
            calls.append(("set", scope.user_id))

        async def delete_my_commands(self, scope):
            calls.append(("delete", scope.user_id))

    await ab.sync_group_command_menus(FakeBot())

    assert ("delete", 222) in calls
    assert ("set", 222) not in calls
    assert ("set", 111) in calls
