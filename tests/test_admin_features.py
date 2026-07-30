"""MVP-2: admin ro'yxati, sozlamalar (bildirishnoma rejimi), shablonlar,
bot pool boshqaruvi (`/addbot`/`/bots`), va case_manager'ning dinamik
shablon + severity integratsiyasi."""

from core import texts
from core.enums import CaseStatus
from core.logic.admins import ensure_admins_seeded, is_admin, list_admin_tg_ids
from core.logic.bot_pool import add_bot, list_bots
from core.logic.settings_store import is_verbose, set_verbose
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
