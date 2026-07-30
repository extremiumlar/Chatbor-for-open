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
    set_bot_active,
    set_bot_phone_format,
)
from core.logic.case_admin import (
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
from tests.test_case_state_machine import _latest_case


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
        updated = await manual_confirm(session, case.id)

    assert updated.status == CaseStatus.CONFIRMED
    assert updated.confirmed_at is not None


async def test_manual_reject_sets_rejected(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2101, "u", "U", "998902222222")
    case = await _latest_case(session_factory, 2101)

    async with session_factory() as session:
        updated = await manual_reject(session, case.id)

    assert updated.status == CaseStatus.REJECTED


async def test_request_redispatch_queues_case_and_sets_flag(seed_bots, make_case_manager, session_factory):
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2102, "u", "U", "998903333333")
    case = await _latest_case(session_factory, 2102)

    async with session_factory() as session:
        updated = await request_redispatch(session, case.id)

    assert updated.status == CaseStatus.NUMBER_RECEIVED
    assert updated.bot_id is None
    assert updated.admin_redispatch_requested is True


async def test_manual_resolution_clears_redispatch_flag(seed_bots, make_case_manager, session_factory):
    """Qayta uzatish so'ralib, keyin qo'lda hal qilinsa — bayroq qolmasligi kerak,
    aks holda Teleton allaqachon yopilgan case'ni dispatch qilardi."""
    await seed_bots(["b1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(2103, "u", "U", "998904444444")
    case = await _latest_case(session_factory, 2103)

    async with session_factory() as session:
        await request_redispatch(session, case.id)
        updated = await manual_confirm(session, case.id)

    assert updated.admin_redispatch_requested is False


async def test_manual_actions_return_none_for_missing_case(session_factory):
    async with session_factory() as session:
        assert await manual_confirm(session, 999) is None
        assert await manual_reject(session, 999) is None
        assert await request_redispatch(session, 999) is None


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

        confirmed = await manual_confirm(session, case.id)
        assert confirmed.updated_at is not None

        rejected = await manual_reject(session, case.id)
        assert rejected.updated_at is not None

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
