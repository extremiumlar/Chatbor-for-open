"""MVP-2: admin ro'yxati, sozlamalar (bildirishnoma rejimi), shablonlar,
bot pool boshqaruvi (`/addbot`/`/bots`), va case_manager'ning dinamik
shablon + severity integratsiyasi."""

import pytest

from core import texts
from core.enums import CaseStatus
from core.logic.admins import (
    ensure_admins_seeded,
    get_admin_by_tg_id,
    is_admin,
    list_admin_tg_ids,
    list_admins,
    set_admin_role,
)
from core.logic.bot_pool import add_bot, list_bots
from core.models import AdminRole
from core.logic.settings_store import (
    get_customer_timeout_seconds,
    get_operator_codes,
    is_verbose,
    set_customer_timeout_seconds,
    set_operator_codes,
    set_verbose,
)
from core.logic.templates import (
    DEFAULTS,
    ensure_templates_seeded,
    get_template,
    list_templates,
    set_template,
)


# --------------------------------------------------------------------------- #
# Admins (TZ 12.2)
# --------------------------------------------------------------------------- #


async def test_admin_seeding_and_lookup_is_idempotent(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        await ensure_admins_seeded(session, [111, 333])  # 111 takrorlanadi, 333 yangi

        assert await is_admin(session, 111) is True
        assert await is_admin(session, 222) is True
        assert await is_admin(session, 333) is True
        assert await is_admin(session, 999) is False

        ids = await list_admin_tg_ids(session)
        assert sorted(ids) == [111, 222, 333]


# --------------------------------------------------------------------------- #
# Audit K-4/J-8 (TZ 14-bo'lim) — rol tizimi
# --------------------------------------------------------------------------- #


async def test_first_seeded_admin_becomes_owner_rest_are_plain_admin(session_factory):
    """Bazada hali birorta ham admin yo'q holatda seed qilinganda, ro'yxatdagi
    BIRINCHI tg_id OWNER bo'ladi — tizimda kamida bitta cheklovsiz admin
    bo'lishi kafolatlanadi (aks holda Q51 ko'rish-cheklovi hech kimga
    to'liq ko'rinish qoldirmasdi)."""
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222, 333])

        first = await get_admin_by_tg_id(session, 111)
        second = await get_admin_by_tg_id(session, 222)
        third = await get_admin_by_tg_id(session, 333)

        assert first.role == AdminRole.OWNER
        assert second.role == AdminRole.ADMIN
        assert third.role == AdminRole.ADMIN


async def test_seeding_again_does_not_create_second_owner(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        await ensure_admins_seeded(session, [111, 222])  # 111 allaqachon bor, 222 yangi

        second = await get_admin_by_tg_id(session, 222)
        assert second.role == AdminRole.ADMIN  # OWNER emas


async def test_set_admin_role_updates_and_returns_none_for_missing(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        admin = await get_admin_by_tg_id(session, 111)

        updated = await set_admin_role(session, admin.id, AdminRole.ROP)
        assert updated.role == AdminRole.ROP

        assert await set_admin_role(session, 9999, AdminRole.ROP) is None


async def test_list_admins_returns_all(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        admins = await list_admins(session)
        assert {a.tg_user_id for a in admins} == {111, 222}


# --------------------------------------------------------------------------- #
# Notify verbose sozlamasi (TZ 9.1)
# --------------------------------------------------------------------------- #


async def test_notify_verbose_defaults_to_off_and_is_toggleable(session_factory):
    async with session_factory() as session:
        assert await is_verbose(session) is False

        await set_verbose(session, True)
        assert await is_verbose(session) is True

        await set_verbose(session, False)
        assert await is_verbose(session) is False


# --------------------------------------------------------------------------- #
# Audit J-9 (TZ 2.2, 4.1) — operator kodlari va mijoz-timeout Adminbot
# orqali jonli sozlanadi, .env faqat boshlang'ich qiymat.
# --------------------------------------------------------------------------- #


async def test_operator_codes_default_from_env_and_are_settable(session_factory):
    async with session_factory() as session:
        default = await get_operator_codes(session)
        assert "90" in default and "97" in default  # .env'dagi standart ro'yxat

        await set_operator_codes(session, ["90", "91", "77"])
        updated = await get_operator_codes(session)
        assert updated == ["90", "91", "77"]


async def test_customer_timeout_seconds_default_from_env_and_are_settable(session_factory):
    async with session_factory() as session:
        default = await get_customer_timeout_seconds(session)
        assert default == 300.0  # .env/config standart qiymati

        await set_customer_timeout_seconds(session, 120)
        assert await get_customer_timeout_seconds(session) == 120.0

        with pytest.raises(ValueError):
            await set_customer_timeout_seconds(session, 0)
        with pytest.raises(ValueError):
            await set_customer_timeout_seconds(session, -5)


# --------------------------------------------------------------------------- #
# Shablonlar (TZ 7.2, 9.2 `/templates`)
# --------------------------------------------------------------------------- #


async def test_template_falls_back_to_default_before_seeding(session_factory):
    async with session_factory() as session:
        assert await get_template(session, "COUPON_REQUEST") == texts.COUPON_REQUEST


async def test_template_seed_is_idempotent_and_matches_defaults(session_factory):
    async with session_factory() as session:
        await ensure_templates_seeded(session)
        await ensure_templates_seeded(session)  # ikkinchi chaqiruv xato bermasligi kerak

        values = await list_templates(session)
        assert values == DEFAULTS


async def test_settemplate_overrides_and_get_template_reflects_it(session_factory):
    async with session_factory() as session:
        await set_template(session, "CONFIRMED", "Yangi tabrik matni!")
        assert await get_template(session, "CONFIRMED") == "Yangi tabrik matni!"

        # Boshqa kalitlar o'zgarmagan holda qoladi.
        assert await get_template(session, "REJECTED") == texts.REJECTED


async def test_settemplate_rejects_unknown_key(session_factory):
    async with session_factory() as session:
        try:
            await set_template(session, "NOMA_LUM_KALIT", "x")
            assert False, "ValueError kutilgan edi"
        except ValueError:
            pass


# --------------------------------------------------------------------------- #
# Bot pool boshqaruvi (`/addbot`, `/bots` — TZ 3.3, 9.5)
# --------------------------------------------------------------------------- #


async def test_add_bot_creates_with_default_format(session_factory):
    async with session_factory() as session:
        bot = await add_bot(session, "new_bot")
        assert bot is not None
        assert bot.phone_format == "+998XXXXXXXXX"
        assert bot.is_active is True
        assert bot.is_busy is False


async def test_add_bot_rejects_duplicate_username(session_factory):
    async with session_factory() as session:
        first = await add_bot(session, "dup_bot")
        assert first is not None

        second = await add_bot(session, "dup_bot")
        assert second is None


async def test_list_bots_returns_all_seeded_bots(session_factory, seed_bots):
    await seed_bots(["b1", "b2", "b3"])
    async with session_factory() as session:
        bots = await list_bots(session)
        assert sorted(b.username for b in bots) == ["b1", "b2", "b3"]


async def test_seeding_same_username_twice_in_one_list_does_not_crash(session_factory, seed_bots):
    # Regressiya: .env'da BOT_POOL_USERNAMES bitta botni bir necha marta
    # sanab o'tishi mumkin — bu holat `bots.username` UNIQUE cheklovini
    # buzib, Teleton ishga tushishida IntegrityError bergan edi.
    await seed_bots(["same_bot", "same_bot", "same_bot"])
    await seed_bots(["same_bot"])  # takroriy chaqiruv ham xato bermasligi kerak

    async with session_factory() as session:
        bots = await list_bots(session)
        assert [b.username for b in bots] == ["same_bot"]


# --------------------------------------------------------------------------- #
# case_manager: shablon o'zgarishi mijozga darhol ta'sir qiladi
# --------------------------------------------------------------------------- #


async def test_overridden_template_is_used_in_customer_reply(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    async with session_factory() as session:
        await set_template(session, "COUPON_REQUEST", "MAXSUS: kupon yuboring!")

    cm = make_case_manager()
    outcome = await cm.handle_phone_detected(801, "user801", "User", "998901234567")
    assert outcome.customer_text == "MAXSUS: kupon yuboring!"


# --------------------------------------------------------------------------- #
# case_manager: alert severity klassifikatsiyasi (TZ 9.1)
# --------------------------------------------------------------------------- #


async def test_confirmed_and_rejected_alerts_are_important(seed_bots, make_case_manager):
    await seed_bots(["bot1"])
    alerts: list[tuple[str, bool]] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append((message, important))

    cm = make_case_manager(alert_sink=capture)
    await cm.handle_phone_detected(802, "user802", "User", "998901234567")
    await cm.handle_coupon_received(802, "111111")  # CONFIRMED

    confirmed_alerts = [a for a in alerts if "CONFIRMED" in a[0]]
    assert confirmed_alerts and all(important for _, important in confirmed_alerts)


async def test_expired_alert_is_not_important(seed_bots, make_case_manager):
    await seed_bots(["bot1"])
    alerts: list[tuple[str, bool]] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append((message, important))

    cm = make_case_manager(alert_sink=capture)
    await cm.handle_phone_detected(803, "user803", "User", "998901234567")
    await cm.handle_coupon_received(803, "222222")  # EXPIRED

    expired_alerts = [a for a in alerts if "EXPIRED" in a[0]]
    assert expired_alerts and all(not important for _, important in expired_alerts)


async def test_duplicate_active_alert_is_always_important(seed_bots, make_case_manager):
    await seed_bots(["bot1", "bot2"])
    alerts: list[tuple[str, bool]] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append((message, important))

    cm = make_case_manager(alert_sink=capture)
    await cm.handle_phone_detected(804, "user804", "User", "998901234567")
    await cm.handle_phone_detected(804, "user804", "User", "998907654321")

    duplicate_alerts = [a for a in alerts if "ikkinchi nomer" in a[0]]
    assert duplicate_alerts and all(important for _, important in duplicate_alerts)
