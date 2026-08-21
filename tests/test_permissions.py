"""Rol asosidagi ruxsatlar — TZ 14 (Q25, Q43).

Ikki narsa tekshiriladi:
1. Matritsaning o'zi to'g'rimi (kim nimaga ega).
2. Majburiy tekshiruv haqiqatan ishlaydimi — ya'ni rolga yopiq buyruq/tugma
   BAJARILMASLIGI (faqat ko'rinmasligi emas).
"""

import datetime
import re

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User as TgUser

from core.logic import permissions as perms
from core.models import Admin, AdminRole


def _admin(role: AdminRole, active: bool = True) -> Admin:
    return Admin(id=1, tg_user_id=100, name="test", role=role, is_active=active)


# --------------------------------------------------------------------------- #
# Matritsaning butunligi
# --------------------------------------------------------------------------- #


def test_every_bot_command_is_in_the_matrix():
    """Yangi buyruq qo'shilib, matritsaga yozilmay qolsa — bu test yiqiladi.

    Aks holda buyruq jimgina himoyasiz qolardi.
    """
    src = open("adminbot_service/bot.py", encoding="utf-8").read()
    in_bot = set(re.findall(r'Command\("([a-z_]+)"\)', src))
    missing = in_bot - set(perms.COMMANDS)
    assert not missing, f"Matritsada yo'q buyruqlar: {sorted(missing)}"


def test_unknown_command_defaults_to_owner_only():
    """Ro'yxatda yo'q buyruq hammaga ochiq bo'lib qolmasligi kerak."""
    for role in AdminRole:
        allowed = perms.can_use_command(_admin(role), "hech_qachon_bolmagan_buyruq")
        assert allowed is (role == AdminRole.OWNER)


def test_owner_can_use_everything():
    owner = _admin(AdminRole.OWNER)
    for command in perms.COMMANDS:
        assert perms.can_use_command(owner, command), command


# --------------------------------------------------------------------------- #
# Rollar bo'yicha kutilgan taqsimot (TZ 14)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "role,command,expected",
    [
        # Kuzatuvchi — faqat ko'rish
        (AdminRole.KUZATUVCHI, "stats", True),
        (AdminRole.KUZATUVCHI, "problems", True),
        (AdminRole.KUZATUVCHI, "bots", True),
        (AdminRole.KUZATUVCHI, "settemplate", False),
        (AdminRole.KUZATUVCHI, "addbot", False),
        (AdminRole.KUZATUVCHI, "setrole", False),
        (AdminRole.KUZATUVCHI, "unrecognized", False),
        # Admin (operator) — murojaat bilan ishlaydi, texnik sozlashga tegmaydi
        (AdminRole.ADMIN, "problems", True),
        (AdminRole.ADMIN, "unrecognized", True),
        (AdminRole.ADMIN, "testcheck", True),
        (AdminRole.ADMIN, "settemplate", False),
        (AdminRole.ADMIN, "setgroup", False),
        (AdminRole.ADMIN, "audit", False),
        (AdminRole.ADMIN, "setrole", False),
        # Dasturchi — texnik sozlash + tashxis
        (AdminRole.DASTURCHI, "addbot", True),
        (AdminRole.DASTURCHI, "settemplate", True),
        (AdminRole.DASTURCHI, "setbotpattern", True),
        (AdminRole.DASTURCHI, "shadow", True),
        # Tashxis: nosozlik qidirayotgan Dasturchi "kim nimani o'zgartirgan"
        # va "kim qaysi rolda" savollariga javob topa olishi kerak.
        (AdminRole.DASTURCHI, "audit", True),
        (AdminRole.DASTURCHI, "admins", True),
        (AdminRole.DASTURCHI, "notify", True),
        # ...lekin o'zgartirish chegarasi saqlanadi:
        (AdminRole.DASTURCHI, "setrole", False),
        (AdminRole.DASTURCHI, "setactive", False),
        (AdminRole.DASTURCHI, "setreporttime", False),
        # Rop — statistika, hisobot, adminlar nazorati
        (AdminRole.ROP, "stats", True),
        (AdminRole.ROP, "audit", True),
        (AdminRole.ROP, "setreporttime", True),
        (AdminRole.ROP, "admins", True),
        (AdminRole.ROP, "addbot", False),
        (AdminRole.ROP, "settemplate", False),
        (AdminRole.ROP, "setrole", False),
    ],
)
def test_role_command_matrix(role, command, expected):
    assert perms.can_use_command(_admin(role), command) is expected


@pytest.mark.parametrize(
    "callback_data,command",
    [
        # Tanilmagan javobni shablonga aylantirish = /addcheckpattern
        ("ucp:5:OTDI", "addcheckpattern"),
        # Bildirishnoma tugmasi = /notify
        ("notify:on", "notify"),
        # "🔌 Sessiyalar" tugmasi = /sessions
        ("nav:sessions", "sessions"),
        # Shablon tahriri = /settemplate
        ("tpl:c:CONFIRMED:edit", "settemplate"),
        # Yangi bot tugmasi = /addbot
        ("newbot", "addbot"),
    ],
)
def test_button_and_command_for_the_same_action_agree(callback_data, command):
    """Bitta amalning ikki yo'li bir xil ruxsatda bo'lishi SHART.

    Jonli sinovda aynan shu buzilgan edi: `ucp` tugmasi `_MANAGE` (Owner/Rop),
    `/addcheckpattern` esa `_TECH` (Owner/Dasturchi) edi. Natijada Dasturchi
    buyruq bilan shablon qo'sha olardi, lekin tugmani bossa rad etilardi;
    Rop esa aksincha. Foydalanuvchi uchun bu tushunarsiz: bir xil ish, ikki
    xil javob.
    """
    tugma_rollari = perms.roles_for_callback(callback_data)
    buyruq_rollari = perms.COMMANDS[command].roles

    assert tugma_rollari == buyruq_rollari, (
        f"{callback_data!r} tugmasi va /{command} buyrug'i bir xil amalni "
        f"bajaradi, lekin ruxsatlari boshqacha:\n"
        f"  tugma : {sorted(r.value for r in tugma_rollari)}\n"
        f"  buyruq: {sorted(r.value for r in buyruq_rollari)}"
    )


def test_only_owner_can_change_roles_and_activation():
    for role in AdminRole:
        admin = _admin(role)
        is_owner = role == AdminRole.OWNER
        assert perms.can_use_command(admin, "setrole") is is_owner
        assert perms.can_use_command(admin, "setactive") is is_owner


# --------------------------------------------------------------------------- #
# Tugmalar — ko'rish va amal ajratilishi
# --------------------------------------------------------------------------- #


def test_callback_key_separates_viewing_from_acting():
    assert perms.callback_key("cs:5") == "cs:view"
    assert perms.callback_key("cs:5:ok") == "cs:act"
    assert perms.callback_key("bot:2") == "bot:view"
    assert perms.callback_key("bot:2:off") == "bot:act"
    assert perms.callback_key("tpl:c:CONFIRMED") == "tpl:view"
    assert perms.callback_key("tpl:c:CONFIRMED:edit") == "tpl:edit"


def test_viewer_can_open_cards_but_not_act_on_them():
    viewer = _admin(AdminRole.KUZATUVCHI)
    assert perms.can_use_callback(viewer, "cs:5") is True       # kartochkani ochish
    assert perms.can_use_callback(viewer, "cs:5:ok") is False   # qo'lda tasdiqlash
    assert perms.can_use_callback(viewer, "bot:2") is True
    assert perms.can_use_callback(viewer, "bot:2:off") is False
    assert perms.can_use_callback(viewer, "tpl:c:CONFIRMED") is True
    assert perms.can_use_callback(viewer, "tpl:c:CONFIRMED:edit") is False


def test_operator_can_act_on_cases_but_not_edit_templates():
    op = _admin(AdminRole.ADMIN)
    assert perms.can_use_callback(op, "cs:5:ok") is True
    assert perms.can_use_callback(op, "safe:5") is True
    assert perms.can_use_callback(op, "block:5") is True
    assert perms.can_use_callback(op, "tpl:c:CONFIRMED:edit") is False
    assert perms.can_use_callback(op, "bot:2:off") is False


def test_unknown_callback_prefix_is_owner_only():
    for role in AdminRole:
        allowed = perms.can_use_callback(_admin(role), "nomalum_prefiks:1")
        assert allowed is (role == AdminRole.OWNER)


# --------------------------------------------------------------------------- #
# Yordam ro'yxati rolga qarab farq qiladi
# --------------------------------------------------------------------------- #


def test_help_lists_only_allowed_commands_per_role():
    from adminbot_service.views import help_for_role

    owner_text = help_for_role(_admin(AdminRole.OWNER))
    viewer_text = help_for_role(_admin(AdminRole.KUZATUVCHI))

    # Owner rol berish buyrug'ini ko'radi, kuzatuvchi — yo'q.
    assert "/setrole" in owner_text
    assert "/setrole" not in viewer_text

    # Ikkovi ham ko'rish buyruqlarini ko'radi.
    assert "/stats" in owner_text and "/stats" in viewer_text

    # Owner ro'yxati kuzatuvchinikidan uzunroq bo'lishi kerak.
    assert len(perms.allowed_commands(_admin(AdminRole.OWNER))) > len(
        perms.allowed_commands(_admin(AdminRole.KUZATUVCHI))
    )


def test_menu_hides_settings_from_operator_and_viewer():
    from adminbot_service.keyboards import BTN_SETTINGS, BTN_STATS, main_menu

    def texts(role):
        return {b.text for row in main_menu(_admin(role)).keyboard for b in row}

    assert BTN_SETTINGS in texts(AdminRole.OWNER)
    assert BTN_SETTINGS in texts(AdminRole.DASTURCHI)
    assert BTN_SETTINGS not in texts(AdminRole.ADMIN)
    assert BTN_SETTINGS not in texts(AdminRole.KUZATUVCHI)
    # Ko'rish tugmalari hammada bo'lishi kerak.
    for role in AdminRole:
        assert BTN_STATS in texts(role)


def test_main_menu_without_admin_shows_everything():
    """Eski chaqiruvlar (rol berilmagan) buzilmasligi kerak."""
    from adminbot_service.keyboards import MAIN_MENU_BUTTONS, main_menu

    shown = {b.text for row in main_menu().keyboard for b in row}
    assert shown == set(MAIN_MENU_BUTTONS)


# --------------------------------------------------------------------------- #
# MAJBURIY TEKSHIRUV — rolga yopiq narsa haqiqatan BAJARILMAYDI
#
# Bu eng muhim qism: tugmani yashirish himoya emas (eski xabardagi tugma
# keyin ham bosiladi). Quyidagilar `RolePermission` middleware'ining
# haqiqatan to'sib qolishini tekshiradi.
# --------------------------------------------------------------------------- #


# DIQQAT: bu yerda HAQIQIY aiogram obyektlari yasaladi, soxta klass emas.
# Middleware ichida `isinstance(event, Message)` tekshiruvi bor — soxta klass
# bilan u tekshiruvdan chetlab o'tib ketardi va test hech narsani
# sinamagan bo'lardi (aynan shu xato bir marta sodir bo'ldi).

_CHAT_PRIVATE = Chat(id=100, type="private")
_CHAT_GROUP = Chat(id=-100123, type="supergroup")


def _tg_user(uid=100):
    return TgUser(id=uid, is_bot=False, first_name="Test")


def _message(text: str, uid: int = 100, group: bool = False) -> Message:
    return Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=_CHAT_GROUP if group else _CHAT_PRIVATE,
        from_user=_tg_user(uid),
        text=text,
    )


def _callback(data: str, uid: int = 100) -> CallbackQuery:
    return CallbackQuery(id="1", from_user=_tg_user(uid), chat_instance="x", data=data)


@pytest.fixture
def run_middleware(monkeypatch):
    """`RolePermission`ni haqiqiy aiogram obyekti bilan chaqiradi.

    `answer` metodi `monkeypatch` orqali almashtiriladi (tarmoqqa chiqmasligi
    uchun) — u testdan keyin avtomatik tiklanadi, shuning uchun testlar
    bir-biriga ta'sir qilmaydi.
    Qaytaradi: (handler chaqirildimi, foydalanuvchiga aytilgan matnlar).
    """
    from adminbot_service.bot import RolePermission

    said: list[str] = []

    async def fake_answer(self, text="", **kw):
        said.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)
    monkeypatch.setattr(CallbackQuery, "answer", fake_answer, raising=False)

    async def _run(event, admin):
        called = False

        async def handler(e, d):
            nonlocal called
            called = True
            return "bajarildi"

        said.clear()
        await RolePermission()(handler, event, {"current_admin": admin})
        return called, list(said)

    return _run


async def test_blocked_command_does_not_reach_handler(run_middleware):
    called, said = await run_middleware(_message("/setrole 123 OWNER"), _admin(AdminRole.ADMIN))

    assert called is False, "rolga yopiq buyruq bajarilib ketdi!"
    assert said, "foydalanuvchiga sabab aytilmadi"
    assert "rolingizga ochiq emas" in said[0]


async def test_allowed_command_reaches_handler(run_middleware):
    called, said = await run_middleware(_message("/stats"), _admin(AdminRole.KUZATUVCHI))
    assert called is True
    assert said == []


async def test_command_with_bot_mention_is_still_checked(run_middleware):
    """Guruhda buyruq `/setrole@BotName` ko'rinishida keladi — bu ham
    tekshiruvdan o'tishi kerak, aks holda guruhda himoya chetlab o'tilardi."""
    called, said = await run_middleware(
        _message("/setrole@O_B_adminsbot 123 OWNER", group=True), _admin(AdminRole.ADMIN)
    )
    assert called is False
    assert "rolingizga ochiq emas" in said[0]


async def test_group_and_private_are_enforced_the_same(run_middleware):
    for group in (False, True):
        called, _ = await run_middleware(
            _message("/addbot yangi", group=group), _admin(AdminRole.ADMIN)
        )
        assert called is False, f"group={group} da o'tkazib yuborildi"


async def test_blocked_callback_does_not_reach_handler(run_middleware):
    called, said = await run_middleware(
        _callback("tpl:c:CONFIRMED:edit"), _admin(AdminRole.ADMIN)
    )
    assert called is False, "rolga yopiq tugma ishlab ketdi!"
    assert said and "ochiq emas" in said[0]


async def test_allowed_callback_reaches_handler(run_middleware):
    called, said = await run_middleware(_callback("cs:5:ok"), _admin(AdminRole.ADMIN))
    assert called is True
    assert said == []


async def test_stale_button_from_higher_role_is_rejected(run_middleware):
    """Eski xabardagi (masalan Owner ko'rgan) tugmani operator bossa —
    ko'rinib turgani bilan bajarilmasligi kerak."""
    for data in ("bot:2:off", "tpl:c:CONFIRMED:edit", "notify:on"):
        called, _ = await run_middleware(_callback(data), _admin(AdminRole.ADMIN))
        assert called is False, data


async def test_blocked_menu_button_press_is_rejected(run_middleware):
    from adminbot_service.keyboards import BTN_SETTINGS

    called, said = await run_middleware(_message(BTN_SETTINGS), _admin(AdminRole.KUZATUVCHI))
    assert called is False
    assert "rolingizga ochiq emas" in said[0]


async def test_inactive_admin_is_rejected_by_filter(session_factory, monkeypatch):
    """`/setactive` bilan o'chirilgan admin botdan uzilishi kerak —
    avval bu tekshirilmasdi va o'chirilgan odam ishlayverardi."""
    import adminbot_service.bot as ab
    from core.logic.admins import ensure_admins_seeded, get_admin_by_tg_id

    async with session_factory() as session:
        await ensure_admins_seeded(session, [4242])
        admin = await get_admin_by_tg_id(session, 4242)
        admin.is_active = False
        await session.commit()

    monkeypatch.setattr(ab, "get_session", session_factory)

    assert await ab.IsAdmin()(_message("/stats", uid=4242)) is False


async def test_active_admin_passes_the_filter(session_factory, monkeypatch):
    """Yuqoridagi testning teskarisi — faol admin o'tishi kerak, aks holda
    `is_active` tekshiruvi hammani to'sib qo'yayotgan bo'lardi."""
    import adminbot_service.bot as ab
    from core.logic.admins import ensure_admins_seeded

    async with session_factory() as session:
        await ensure_admins_seeded(session, [4343])

    monkeypatch.setattr(ab, "get_session", session_factory)

    result = await ab.IsAdmin()(_message("/stats", uid=4343))
    assert isinstance(result, dict)
    assert result["current_admin"].tg_user_id == 4343


# --------------------------------------------------------------------------- #
# T-9 — HAQIQIY yo'l orqali tekshiruv (router propagate_event)
#
# Yuqoridagi `run_middleware` testlari middleware'ni QO'LDA chaqiradi va
# `current_admin`ni o'zi beradi. Bu ishlashini ko'rsatadi, lekin uning
# HAQIQATAN ulanganini ko'rsatmaydi: aiogram'da tashqi (outer) middleware
# router filtrlaridan OLDIN ishlaydi, ya'ni `IsAdmin` hali `current_admin`ni
# bermagan bo'ladi va tekshiruv `admin is None` deb jimgina o'tkazib
# yuborardi — barcha buyruqlar tekshirilmay ketardi. Quyidagilar xabarni
# haqiqiy router orqali o'tkazadi, shuning uchun bu xatoni ushlaydi.
# --------------------------------------------------------------------------- #


def test_role_check_is_wired_as_inner_middleware_for_messages():
    """Xabarlar uchun `RolePermission` ICHKI middleware bo'lishi shart.

    Tashqi bo'lsa — filtrlardan oldin ishlab, `current_admin`siz qolib,
    hech narsani tekshirmaydi.
    """
    from adminbot_service.bot import RolePermission, admin_router

    obs = admin_router.message
    assert any(isinstance(m, RolePermission) for m in obs.middleware), (
        "RolePermission xabarlar uchun ichki middleware sifatida ulanmagan"
    )
    assert not any(isinstance(m, RolePermission) for m in obs.outer_middleware), (
        "RolePermission tashqi middleware sifatida qolgan — u yerda "
        "`current_admin` hali yo'q, demak tekshiruv ishlamaydi"
    )


@pytest.fixture
def feed_message(session_factory, monkeypatch):
    """Xabarni HAQIQIY `admin_router` orqali o'tkazadi (filtr + middleware +
    handler) va foydalanuvchiga qaytgan matnlarni qaytaradi."""
    import adminbot_service.bot as ab

    said: list[str] = []

    async def fake_answer(self, text="", **kw):
        said.append(text)
        return None

    monkeypatch.setattr(ab, "get_session", session_factory)
    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)

    async def _feed(text: str, uid: int = 100) -> list[str]:
        said.clear()
        await ab.admin_router.propagate_event(
            "message", _message(text, uid=uid), bot=None, event_update=None
        )
        return list(said)

    return _feed


async def _seed_admin(session_factory, tg_id: int, role: AdminRole):
    from core.logic.admins import ensure_admins_seeded, get_admin_by_tg_id, set_admin_role

    async with session_factory() as session:
        await ensure_admins_seeded(session, [tg_id])
        admin = await get_admin_by_tg_id(session, tg_id)
        await set_admin_role(session, admin.id, role)


@pytest.mark.parametrize(
    "role,command",
    [
        (AdminRole.KUZATUVCHI, "/setrole 999 ADMIN"),
        (AdminRole.ADMIN, "/setrole 999 ADMIN"),
        (AdminRole.ADMIN, "/setgroup -100999"),
        (AdminRole.KUZATUVCHI, "/setreporttime 20:30"),
        (AdminRole.ADMIN, "/addcheckpattern OTDI test"),
    ],
)
async def test_forbidden_command_is_blocked_end_to_end(
    session_factory, feed_message, role, command
):
    """Rolga yopiq buyruq handler'gacha yetib bormasligi kerak."""
    await _seed_admin(session_factory, 100, role)

    said = await feed_message(command)

    assert said, "hech qanday javob qaytmadi — tekshiruv jim o'tkazib yubordi"
    assert "rolingizga ochiq emas" in said[0], said


async def test_allowed_command_still_reaches_its_handler(session_factory, feed_message):
    """Teskari tomon: ruxsat bor bo'lsa buyruq haqiqatan bajarilishi kerak
    (aks holda yuqoridagi test hamma narsani to'sib qo'yish bilan ham
    o'tib ketardi)."""
    await _seed_admin(session_factory, 100, AdminRole.OWNER)

    said = await feed_message("/setrole 999 ADMIN")

    assert said
    assert "rolingizga ochiq emas" not in said[0]
    # 999 bazada yo'q — handler ishlaganini shu javob tasdiqlaydi.
    assert "topilmadi" in said[0].lower()


def test_handler_checks_do_not_contradict_permission_table():
    """Handler ichida qo'lda yozilgan rol tekshiruvi qolmaganini kafolatlaydi.

    Aks holda jadval va amaliyot yana ajralib ketadi: buyruq /help da
    ko'rinadi, middleware o'tkazadi, handler esa rad etadi.
    """
    src = open("adminbot_service/bot.py", encoding="utf-8").read()
    # Izohlar hisobga olinmaydi — ular tekshiruv emas, tushuntirish.
    kod = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    # Aynan CHAQIRUVCHINING roli tekshirilishi qidiriladi (`current_admin`),
    # chunki ruxsat gati shundaydir. Boshqa `AdminRole` solishtirishlari
    # (masalan "yangi rol OWNER'mi") ruxsat emas — ular tegilmaydi.
    taqiqlangan = re.findall(r"current_admin\.role\s*(?:not in|in|==|!=)[^\n]*", kod)
    assert not taqiqlangan, (
        "Handler ichida qo'lda rol tekshiruvi topildi — ruxsat faqat "
        f"core/logic/permissions.py orqali berilishi kerak: {taqiqlangan}"
    )
