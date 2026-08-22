"""Jonli sinov topilmalari bo'yicha tuzatishlar — TUZATISH_TOPSHIRIQLARI.md.

Har test topshiriq raqami bilan belgilangan (T-1, T-2, ...) — kelajakda
regressiya bo'lsa, qaysi topilma qaytganini darhol bilish uchun.
"""

import datetime

import pytest
from aiogram.types import Chat, Message, User as TgUser

from core.logic.settings_store import is_shadow_mode, set_shadow_mode
from core.models import Admin, AdminRole

_CHAT = Chat(id=1, type="private")


def _msg(text: str, uid: int = 100) -> Message:
    return Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=_CHAT,
        from_user=TgUser(id=uid, is_bot=False, first_name="Test"),
        text=text,
    )


@pytest.fixture
def shadow_env(session_factory, monkeypatch):
    """`/shadow`ni HAQIQIY router orqali o'tkazadi.

    T-9 dan keyin rol tekshiruvi handler ichida emas, `RolePermission`
    middleware'da. Handler'ni to'g'ridan-to'g'ri chaqirsak, o'sha tekshiruv
    chetlab o'tilar va test uni sinamagan bo'lardi — shuning uchun xabar
    filtr + middleware + handler zanjirining hammasidan o'tkaziladi.
    """
    import adminbot_service.bot as ab
    from core.logic.admins import ensure_admins_seeded, get_admin_by_tg_id, set_admin_role

    said: list[str] = []

    async def fake_answer(self, text="", **kw):
        said.append(text)

    monkeypatch.setattr(ab, "get_session", session_factory)
    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)

    async def call(arg: str | None, role: AdminRole = AdminRole.OWNER):
        said.clear()
        async with session_factory() as session:
            await ensure_admins_seeded(session, [100])
            admin = await get_admin_by_tg_id(session, 100)
            await set_admin_role(session, admin.id, role)

        text = "/shadow" + (f" {arg}" if arg else "")
        await ab.admin_router.propagate_event(
            "message", _msg(text), bot=None, event_update=None
        )
        async with session_factory() as session:
            return await is_shadow_mode(session), list(said)

    return call


# --------------------------------------------------------------------------- #
# T-1 — argumentsiz /shadow rejimni O'ZGARTIRMASLIGI kerak
# --------------------------------------------------------------------------- #


async def test_t1_bare_shadow_only_reports_and_never_toggles(shadow_env, session_factory):
    """Jonli sinovda admin "qaysi rejimdaman?" deb yozgan buyruq xavfsizlik
    tormozini jimgina ochib yuborgan edi (2 marta)."""
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    # Argumentsiz — qiymat o'zgarmasligi kerak, faqat holat aytiladi.
    value, said = await shadow_env(None)
    assert value is True, "argumentsiz /shadow rejimni o'zgartirib yubordi!"
    assert "YOQILGAN" in said[0]

    # Ikki marta chaqirsa ham o'zgarmaydi (avval aynan shu almashtirardi).
    value, _ = await shadow_env(None)
    assert value is True


async def test_t1_explicit_off_and_on(shadow_env, session_factory):
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("off")
    assert value is False
    assert "O'CHIRILDI" in said[0]

    value, said = await shadow_env("on")
    assert value is True
    assert "YOQILDI" in said[0]


async def test_t1_invalid_argument_changes_nothing(shadow_env, session_factory):
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("xyz")
    assert value is True
    assert "Format" in said[0]


async def test_t1_repeated_same_value_is_a_noop(shadow_env, session_factory):
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("on")
    assert value is True
    assert "allaqachon" in said[0]


async def test_t1_role_without_permission_cannot_change(shadow_env, session_factory):
    """Ruxsatsiz rol soya rejimini o'zgartira olmasligi kerak.

    T-9 dan keyin buyruq BUTUNLAY rolga bog'liq (`permissions.COMMANDS`da
    `_TECH` = Owner + Dasturchi), shuning uchun oddiy admin uni ko'ra ham
    olmaydi. Soya rejimi holati unga "🔧 Tizim holati" ekranida ko'rinadi —
    `test_t9_shadow_state_is_visible_in_health` ga qarang.
    """
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("off", role=AdminRole.ADMIN)
    assert value is True, "ruxsatsiz rol soya rejimini o'chirib yubordi!"
    assert "ochiq emas" in said[0]

    # Kuzatuvchi ham o'zgartira olmaydi.
    value, said = await shadow_env("off", role=AdminRole.KUZATUVCHI)
    assert value is True
    assert "ochiq emas" in said[0]


# --------------------------------------------------------------------------- #
# T-2 — soya rejimi relay qatlamida ham hurmat qilinsin
# --------------------------------------------------------------------------- #


async def test_t2_relay_blocks_customer_writes_in_shadow_mode(
    session_factory, monkeypatch
):
    """§6.4.6: soya rejimida mijozga HECH NARSA yozilmaydi — istisno yo'q.

    Avval bu tekshiruv faqat `result_flow`da bor edi, relay esa
    `is_shadow_mode`ni umuman chaqirmasdi: jonli sinovda mijoz §5.3
    shablonini 3 marta, "allaqachon ovoz berilgan"ni 1 marta oldi.
    """
    import teleton_service.manual_relay as relay

    monkeypatch.setattr(relay, "get_session", session_factory)

    async with session_factory() as session:
        await set_shadow_mode(session, True)
    assert await relay.customer_writes_allowed() is False

    async with session_factory() as session:
        await set_shadow_mode(session, False)
    assert await relay.customer_writes_allowed() is True


async def test_t2_shadow_mode_defaults_to_on(session_factory, monkeypatch):
    """Standart qiymat YOQILGAN bo'lishi kerak — sozlanmagan tizim
    tasodifan mijozlarga yozib yubormasin."""
    import teleton_service.manual_relay as relay

    monkeypatch.setattr(relay, "get_session", session_factory)
    # Hech narsa yozilmagan baza — soya yoqilgan deb hisoblanadi.
    assert await relay.customer_writes_allowed() is False


# --------------------------------------------------------------------------- #
# T-3 — `/check` aniq tanilsin, `/checkpatterns` yeb qo'yilmasin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/check", True),
        ("/check +998901234567", True),
        ("/check@O_B_adminsbot", True),
        ("/CHECK", True),
        ("/checkpatterns", False),          # adminbot buyrug'i — o'chirilmasin
        ("/checkpattern sinov", False),
        ("/checkpatterns@O_B_adminsbot", False),
        ("/testcheck bor", False),
        ("salom /check", False),            # gap o'rtasida — buyruq emas
        ("", False),
    ],
)
def test_t3_check_command_is_matched_exactly(text, expected):
    """`startswith("/check")` `/checkpatterns` ni ham ushlab, relay uni
    o'chirib yuborardi — jonli sinovda 3/3 urinishda buyruq yo'qoldi."""
    from teleton_service.manual_relay import is_check_command

    assert is_check_command(text) is expected


# --------------------------------------------------------------------------- #
# T-4 — adminbot nazorat guruhida jim tursin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "chat_type,text,expected",
    [
        # Lichkada hamma narsa o'tadi.
        ("private", "salom", True),
        ("private", "998901234567", True),
        ("private", "/stats", True),
        ("private", None, True),
        # Guruhda endi ISTALGAN buyruq ishlaydi (foydalanuvchi qarori).
        ("supergroup", "/setgroup", True),
        ("supergroup", "/help", True),
        ("supergroup", "/help@O_B_adminsbot", True),
        ("group", "/setgroup", True),
        ("supergroup", "/stats", True),
        ("supergroup", "/vstats", True),
        # Lekin caption/rasm hamon to'siladi — T-4 spam himoyasi saqlanadi.
        ("supergroup", "salom", False),
        ("supergroup", "998901234567 KOD-12", False),  # caption — nomer bor
        ("supergroup", None, False),                   # rasm (matnsiz)
        ("supergroup", "", False),
    ],
)
def test_t4_bot_answers_in_group_only_for_commands(chat_type, text, expected):
    """Guruhga forward qilingan rasm va caption (buyruq emas) botni ishga
    tushirib, arxivni "Tushunmadim" javoblari bilan to'ldirardi (kuniga
    ~140 ta). Buyruqlarning o'zi endi guruhda ham ishlaydi."""
    from adminbot_service.bot import should_handle_in_chat

    assert should_handle_in_chat(chat_type, text) is expected


# --------------------------------------------------------------------------- #
# T-5 — admin/tekshiruvchi xabarlari mijoz deb qabul qilinmasin
# --------------------------------------------------------------------------- #


async def test_t5_admin_accounts_are_recognised_as_service(session_factory, monkeypatch):
    """Jonli sinovda tekshiruvchiga ketgan so'rov o'sha akkauntning O'Z
    klienti tomonidan "yangi mijoz nomeri" deb o'qilib, soxta case va alert
    yaratgan edi."""
    import teleton_service.manual_relay as relay
    from core.logic.admins import ensure_admins_seeded

    monkeypatch.setattr(relay, "get_session", session_factory)
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])

    await relay._refresh_admin_tg_ids()

    assert relay.is_service_account(111) is True   # admin — mijoz emas
    assert relay.is_service_account(222) is True
    assert relay.is_service_account(999) is False  # haqiqiy mijoz


async def test_t5_setchecker_warns_when_checker_is_a_watched_admin(
    session_factory, monkeypatch
):
    """Tekshiruvchi ayni vaqtda kuzatilayotgan admin bo'lsa — ogohlantirish."""
    import adminbot_service.bot as ab
    from core.logic.admins import (
        ensure_admins_seeded,
        get_admin_by_tg_id,
        refresh_admin_identity,
    )

    monkeypatch.setattr(ab, "get_session", session_factory)

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        admin = await get_admin_by_tg_id(session, 111)
        await refresh_admin_identity(session, admin, "Tekshiruvchi Aka", "checker1")

        # Raqamli id bo'yicha ham, username bo'yicha ham topilishi kerak.
        assert await ab._checker_is_watched_admin(session, "111") is not None
        assert await ab._checker_is_watched_admin(session, "@checker1") is not None
        assert await ab._checker_is_watched_admin(session, "checker1") is not None
        # Aloqasi yo'q akkaunt — ogohlantirish kerak emas.
        assert await ab._checker_is_watched_admin(session, "@boshqa_odam") is None


# --------------------------------------------------------------------------- #
# T-8 — TZ v2 4.3 "Sessiyalar" bo'limi
# --------------------------------------------------------------------------- #


async def _seed_sessions(session_factory):
    """Uchta admin, uchta har xil holatdagi sessiya."""
    from core.models import AdminSession, SessionStatus

    async with session_factory() as session:
        rows = [
            (Admin(tg_user_id=11, name="11", role=AdminRole.OWNER, full_name="Ali Vali"),
             SessionStatus.CONNECTED, "sessions_ali", None),
            (Admin(tg_user_id=22, name="22", role=AdminRole.ADMIN, tg_username="beka"),
             SessionStatus.DISCONNECTED, "sessions_beka", None),
            (Admin(tg_user_id=33, name="33", role=AdminRole.ADMIN, is_active=False),
             SessionStatus.AUTH_LOST, "sessions_dilnoza", "AuthKeyUnregisteredError"),
        ]
        for admin, status, name, err in rows:
            session.add(admin)
            await session.flush()
            session.add(
                AdminSession(
                    admin_id=admin.id,
                    session_name=name,
                    phone="+99890000000" + str(admin.tg_user_id)[0],
                    status=status,
                    last_seen_at=datetime.datetime(2026, 8, 18, 5, 30),
                    last_error=err,
                )
            )
        await session.commit()


async def test_t8_list_admin_sessions_returns_every_session_with_owner(session_factory):
    """Jonli sinovda sessiya holatini ko'rish imkoni umuman yo'q edi —
    baza qatlami tayyor bo'lsa ham (TZ v2 4.3)."""
    from core.logic.admins import list_admin_sessions

    await _seed_sessions(session_factory)
    async with session_factory() as session:
        rows = await list_admin_sessions(session)

    assert len(rows) == 3
    # Har qatorda sessiya + EGASI birga kelishi kerak (ikkinchi so'rovsiz).
    assert [a.tg_user_id for _, a in rows] == [11, 22, 33]
    assert [s.session_name for s, _ in rows] == [
        "sessions_ali",
        "sessions_beka",
        "sessions_dilnoza",
    ]


async def test_t8_sessions_text_marks_auth_lost_in_red(session_factory):
    """🔴 AUTH_LOST — eng muhim holat: qayta login qilinmasa o'sha adminning
    mijozlari umuman ko'rinmaydi."""
    from adminbot_service import views
    from core.logic.admins import list_admin_sessions

    await _seed_sessions(session_factory)
    async with session_factory() as session:
        rows = await list_admin_sessions(session)

    text = views.sessions_text(rows)

    assert "🟢" in text and "🟡" in text and "🔴" in text
    assert "Ali Vali" in text          # to'liq ism
    assert "@beka" in text             # username
    assert "AuthKeyUnregisteredError" in text
    assert "1 ta sessiyada avtorizatsiya yo'qolgan" in text
    # Nofaol adminning sessiyasi ATAYLAB ko'tarilmagan — buni aytishi kerak.
    assert "Admin nofaol" in text
    # Oxirgi faollik Toshkent vaqtida (UTC 05:30 -> 10:30).
    assert "10:30" in text


async def test_t8_sessions_text_without_last_seen(session_factory):
    """Hech qachon ulanmagan sessiya bo'sh joy emas, tushunarli izoh
    ko'rsatsin."""
    from adminbot_service import views
    from core.logic.admins import list_admin_sessions
    from core.models import AdminSession, SessionStatus

    async with session_factory() as session:
        admin = Admin(tg_user_id=44, name="44", role=AdminRole.ADMIN)
        session.add(admin)
        await session.flush()
        session.add(
            AdminSession(
                admin_id=admin.id,
                session_name="sessions_yangi",
                phone="+998900000044",
                status=SessionStatus.DISCONNECTED,
            )
        )
        await session.commit()
        rows = await list_admin_sessions(session)

    text = views.sessions_text(rows)
    assert "hali bir marta ham ulanmagan" in text


async def test_t8_handler_explains_when_no_sessions(session_factory, monkeypatch):
    """Sessiya yo'q bo'lsa — bo'sh ro'yxat emas, nima qilish kerakligi."""
    import adminbot_service.bot as ab

    monkeypatch.setattr(ab, "get_session", session_factory)
    text = await ab._sessions_text()

    assert "Hech qanday admin sessiyasi ulanmagan" in text
    assert "add_admin_session" in text


def test_t8_sessions_command_is_in_permission_matrix():
    """Matritsaga yozilmagan buyruq faqat OWNER'ga ochiq bo'lib qoladi —
    Rop va Dasturchi ham ko'ra olishi kerak (TZ v2 4.3)."""
    from core.logic import permissions as perms

    assert "sessions" in perms.COMMANDS
    for role in (AdminRole.OWNER, AdminRole.ROP, AdminRole.DASTURCHI):
        assert perms.can_use_command(_admin_with_role(role), "sessions")
    for role in (AdminRole.ADMIN, AdminRole.KUZATUVCHI):
        assert not perms.can_use_command(_admin_with_role(role), "sessions")


def test_t8_sessions_button_matches_the_command_permission():
    """Tugma buyruqdan ochiqroq bo'lib qolmasin: `nav:*` odatda hamma uchun
    ochiq, shuning uchun `nav:sessions` alohida yozilgan."""
    from core.logic import permissions as perms

    assert perms.callback_key("nav:sessions") == "nav:sessions"
    assert perms.callback_key("nav:settings") == "nav"  # boshqalari o'zgarmagan
    assert perms.can_use_callback(_admin_with_role(AdminRole.DASTURCHI), "nav:sessions")
    assert not perms.can_use_callback(_admin_with_role(AdminRole.KUZATUVCHI), "nav:sessions")


def _admin_with_role(role: AdminRole) -> Admin:
    return Admin(id=1, tg_user_id=1, name="x", role=role, is_active=True)


# --------------------------------------------------------------------------- #
# T-9 — jadval va handler tekshiruvlari birlashtirildi
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    ["setgroup", "setchecker", "shadow", "addcheckpattern", "delcheckpattern", "uyqu"],
)
def test_t9_tech_commands_are_open_to_dasturchi(command):
    """Avvalgi zidlik: jadval "Dasturchi ham" derdi, handler esa "faqat
    Owner/Rop" deb rad etardi — buyruq /help da ko'rinar, lekin ishlamasdi.
    TZ 14 "Dasturchi — texnik sozlash" bo'yicha jadval to'g'ri.
    """
    from core.logic import permissions as perms

    assert perms.can_use_command(_admin_with_role(AdminRole.DASTURCHI), command)
    assert perms.can_use_command(_admin_with_role(AdminRole.OWNER), command)
    assert not perms.can_use_command(_admin_with_role(AdminRole.ADMIN), command)


async def test_t9_dasturchi_can_actually_change_shadow_mode(shadow_env, session_factory):
    """Zidlikning amaliy tomoni: Dasturchi endi haqiqatan bajara olishi
    kerak (avval handler uni rad etardi)."""
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("off", role=AdminRole.DASTURCHI)

    assert value is False, "Dasturchi texnik sozlashni bajara olmadi"
    assert "O'CHIRILDI" in said[0]


def test_t9_shadow_state_is_visible_in_health():
    """`/shadow` endi oddiy adminga yopiq — lekin soya rejimida mijozga
    HECH NARSA yozilmaydi, buni bilmagan operator tizimni buzilgan deb
    o'ylaydi. Shuning uchun holat hammaga ochiq "Tizim holati"da ko'rinadi.
    """
    from adminbot_service import views

    yoqilgan = views.health_text([], [], True, shadow=True)
    ochiq = views.health_text([], [], True, shadow=False)

    assert "Soya rejimi" in yoqilgan and "YOQILGAN" in yoqilgan
    assert "Soya rejimi" in ochiq and "o'chirilgan" in ochiq
    # Eski chaqiruvlar (shadow berilmagan) baribir ishlashi kerak.
    assert "Soya rejimi" not in views.health_text([], [], True)


# --------------------------------------------------------------------------- #
# T-12 — guruh caption'ida admin ismi raqam bo'lib qolmasin
# --------------------------------------------------------------------------- #


class _FakeMe:
    def __init__(self, first_name=None, last_name=None, username=None):
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class _FakeClient:
    """`_start_one` ishlatadigan minimal Telethon yuzasi."""

    def __init__(self, *args, **kwargs):
        self.flood_sleep_threshold = None
        self.connected = False
        self.me = _FakeMe("Abduqahhor", "Suvonov", "abduqahhor")

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return self.me

    async def disconnect(self):
        self.connected = False


async def _seed_session_row(session_factory, tg_id=6644467393):
    """Ismi hali faqat raqam bo'lgan admin + uning sessiyasi."""
    from core.models import AdminSession

    async with session_factory() as session:
        admin = Admin(tg_user_id=tg_id, name=str(tg_id), role=AdminRole.ADMIN)
        session.add(admin)
        await session.flush()
        row = AdminSession(
            admin_id=admin.id, session_name="s1", phone="+998901112233"
        )
        session.add(row)
        await session.commit()
        return admin.id, row.id


def _manager(session_factory):
    from teleton_service.multi_client import MultiClientManager

    async def _alert(message: str, important: bool = True) -> None:
        pass

    return MultiClientManager(
        session_factory=session_factory,
        api_id=1,
        api_hash="x",
        sessions_dir=".",
        alert_sink=_alert,
    )


async def test_t12_identity_is_refreshed_from_the_telethon_session(session_factory):
    """Jonli sinovda adminbotga hech qachon yozmagan admin guruh
    caption'larida `6644467393` bo'lib chiqardi — TZ §5.2 esa ism talab
    qiladi."""
    from teleton_service.multi_client import ManagedClient

    admin_id, row_id = await _seed_session_row(session_factory)
    manager = _manager(session_factory)
    client = _FakeClient()

    async with session_factory() as session:
        admin = await session.get(Admin, admin_id)
    managed = ManagedClient(
        admin_id=admin_id, admin_name=admin.name, session_row_id=row_id, client=client
    )

    await manager._refresh_identity(client, admin, managed)

    # Bazada yozildi.
    async with session_factory() as session:
        saqlangan = await session.get(Admin, admin_id)
    assert saqlangan.full_name == "Abduqahhor Suvonov"
    assert saqlangan.tg_username == "abduqahhor"
    assert saqlangan.name == "Abduqahhor Suvonov"

    # Handler'larga uzatiladigan OBYEKTDA ham — caption aynan shuni o'qiydi.
    assert admin.name == "Abduqahhor Suvonov"
    assert managed.admin_name == "Abduqahhor Suvonov"


async def test_t12_refresh_failure_does_not_kill_the_session(session_factory):
    """Ism — qulaylik; uning ustidan butun sessiyani yiqitib bo'lmaydi."""
    from teleton_service.multi_client import ManagedClient

    admin_id, row_id = await _seed_session_row(session_factory)
    manager = _manager(session_factory)

    class _Broken(_FakeClient):
        async def get_me(self):
            raise RuntimeError("tarmoq yo'q")

    client = _Broken()
    async with session_factory() as session:
        admin = await session.get(Admin, admin_id)
    managed = ManagedClient(
        admin_id=admin_id, admin_name=admin.name, session_row_id=row_id, client=client
    )

    await manager._refresh_identity(client, admin, managed)  # ko'tarilmasligi kerak

    assert admin.name == str(admin.tg_user_id)  # eski nom qoldi


async def test_t12_start_one_actually_calls_the_refresh(session_factory, monkeypatch):
    """Kod yozilgani yetmaydi — u HAQIQATAN chaqirilishi kerak.

    `refresh_admin_identity` avval ham mavjud edi, faqat relay tomonidan
    hech qachon chaqirilmasdi — muammo aynan shunda edi.
    """
    import teleton_service.multi_client as mc

    admin_id, row_id = await _seed_session_row(session_factory)
    monkeypatch.setattr(mc, "TelegramClient", _FakeClient)

    manager = _manager(session_factory)
    async with session_factory() as session:
        admin = await session.get(Admin, admin_id)
        row = await session.get(mc.AdminSession, row_id)

    ok = await manager._start_one(row, admin, lambda client, a: None)

    assert ok is True
    assert admin.name == "Abduqahhor Suvonov", "sessiya ulanganda ism yangilanmadi"
    assert manager.clients[admin_id].admin_name == "Abduqahhor Suvonov"


# --------------------------------------------------------------------------- #
# T-13 — caption HTML rejimida yuborilishi
# --------------------------------------------------------------------------- #


def test_t13_caption_is_sent_with_html_parse_mode():
    """Caption ichida `tg://user?id=` havolasi bor. `parse_mode` berilmasa
    Telethon uni xom matn qilib yuboradi va guruhda `<a href=...>` ko'rinadi.

    Chaqiruv AST orqali topiladi — matn qidiruvi kod formatlanishi
    o'zgarganda yolg'on o'tib ketardi.
    """
    import ast

    manba = open("teleton_service/manual_relay.py", encoding="utf-8").read()
    topildi = []
    for node in ast.walk(ast.parse(manba)):
        if not isinstance(node, ast.Call):
            continue
        # `<biror>.send_message(...)` chaqiruvlari orasidan caption'lisi.
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "send_message"):
            continue
        uzatilgan = ast.unparse(node)
        if "decision.caption" not in uzatilgan:
            continue
        topildi.append(uzatilgan)
        kalitlar = {kw.arg for kw in node.keywords}
        assert "parse_mode" in kalitlar, (
            f"caption HTML rejimisiz yuborilyapti — havola xom matn "
            f"bo'lib ko'rinadi: {uzatilgan}"
        )

    assert topildi, "caption yuboradigan send_message chaqiruvi topilmadi"


# --------------------------------------------------------------------------- #
# T-14 — relay kuponni nomer bilan birga uzatishi
# --------------------------------------------------------------------------- #


def test_t14_relay_passes_the_phone_with_the_coupon():
    """`handle_coupon_detected` `phone` parametrini qabul qilishi yetmaydi —
    relay uni HAQIQATAN uzatishi kerak.

    Ikkita chaqiruv bo'lishi kutiladi:
      * nomer va kupon bitta xabarda  -> `phone=` bilan;
      * faqat kupon (alohida xabar)   -> `phone`siz (oxirgi ochiq case).
    """
    import ast

    manba = open("teleton_service/manual_relay.py", encoding="utf-8").read()
    chaqiruvlar = [
        node
        for node in ast.walk(ast.parse(manba))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "handle_coupon_detected"
    ]

    assert len(chaqiruvlar) == 2, [ast.unparse(c) for c in chaqiruvlar]
    phone_bilan = [c for c in chaqiruvlar if any(kw.arg == "phone" for kw in c.keywords)]
    assert len(phone_bilan) == 1, (
        "nomer+kupon bitta xabarda kelgan holatda `phone=` uzatilmayapti — "
        "kupon yana oxirgi ochiq case'ga tushadi: "
        f"{[ast.unparse(c) for c in chaqiruvlar]}"
    )


# --------------------------------------------------------------------------- #
# T-16 — pytest jonli log fayliga yozmasin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fayl",
    [
        "adminbot_service/bot.py",
        "teleton_service/manual_relay.py",
        "teleton_service/relay.py",
    ],
)
def test_t16_logging_is_not_configured_at_import_time(fayl):
    """`configure_logging` modul darajasida turmasligi kerak.

    Turgan bo'lsa, testlar modulni import qilishi bilanoq jonli
    `logs/*.log` fayli ochiladi va test uydirmalari o'sha yerga yoziladi —
    haqiqiy xato izlashda chalg'itadi (o'lchandi: bitta `pytest -q` dan
    keyin adminbot.log ~8.5 KB ga o'sgan).
    """
    import ast

    daraxt = ast.parse(open(fayl, encoding="utf-8").read())
    modul_darajasida = [
        ast.unparse(node.value)
        for node in daraxt.body  # faqat eng yuqori daraja — funksiya ichi emas
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "configure_logging"
    ]
    assert not modul_darajasida, (
        f"{fayl}: `configure_logging` modul darajasida chaqirilyapti — "
        f"uni `main()` ichiga ko'chiring: {modul_darajasida}"
    )

    # ...lekin butunlay o'chirib yuborilmagan bo'lsin ham: aks holda xizmat
    # jonli ishlaganda hech qanday log fayli yozilmay qolardi va bu test
    # buni sezmasdan o'tib ketardi.
    ichkarida = [
        node
        for node in ast.walk(daraxt)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "configure_logging"
    ]
    assert ichkarida, f"{fayl}: `configure_logging` umuman chaqirilmayapti"


def test_t16_importing_the_bot_creates_no_log_file(tmp_path):
    """Yuqoridagi tuzilma tekshiruvining amaliy tasdig'i: toza jarayonda
    modulni import qilib, hech qanday log fayli yaratilmasligini ko'ramiz."""
    import os
    import subprocess
    import sys

    muhit = dict(os.environ, LOG_DIR=str(tmp_path))
    natija = subprocess.run(
        [
            sys.executable,
            "-c",
            "import adminbot_service.bot, teleton_service.manual_relay",
        ],
        env=muhit,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    assert natija.returncode == 0, natija.stderr
    assert list(tmp_path.glob("*.log")) == [], "import paytida log fayli yaratildi"


# --------------------------------------------------------------------------- #
# K-3 — soya rejimi o'chirilayotganda shablonlar holati aniq aytilsin
#
# Bu topilma "kod emas, SOZLAMA" deb belgilangan (shablonlar mazmunini faqat
# foydalanuvchi biladi), lekin xavf aynan `/shadow off` lahzasida yuz beradi:
# shablonlar to'liq bo'lmasa, "bazada bor emas" javobi O'TDI deb o'qilib,
# ovozi o'tmagan mijozga "tasdiqlandi" yoziladi. Buyruq endi qaysi
# kategoriya bo'shligini nomma-nom aytadi (bloklamaydi — bu superadmin
# qarori).
# --------------------------------------------------------------------------- #


async def test_k3_shadow_off_names_the_empty_pattern_categories(shadow_env, session_factory):
    """Hech qanday shablon kiritilmagan holat — eng xavflisi."""
    async with session_factory() as session:
        await set_shadow_mode(session, True)

    value, said = await shadow_env("off")

    assert value is False  # o'chirish bloklanmaydi
    matn = said[0]
    assert "birorta ham shablon yo'q" in matn
    assert "CHECK_PASSED" in matn and "CHECK_FAILED" in matn and "CHECK_ERROR" in matn
    # Xavfning O'ZI tushuntirilsin, quruq ogohlantirish emas.
    assert "bazada bor emas" in matn


async def test_k3_shadow_off_is_calm_when_all_categories_are_filled(
    shadow_env, session_factory
):
    """Shablonlar bor bo'lsa vahima qilinmasin — aks holda ogohlantirish
    ma'nosini yo'qotadi va e'tibordan qoladi."""
    from core.logic.check_patterns import CheckCategory, add_pattern

    async with session_factory() as session:
        await set_shadow_mode(session, True)
        await add_pattern(session, CheckCategory.CHECK_PASSED, "o'tdi")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "o'tmadi")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")

    value, said = await shadow_env("off")

    assert value is False
    assert "birorta ham shablon yo'q" not in said[0]
    assert "Uchala kategoriyada shablon bor" in said[0]


async def test_k3_partial_patterns_still_warn(shadow_env, session_factory):
    """Jonli sinovdagi aniq holat: PASSED to'ldirilgan, FAILED esa amalda
    ishlamaydi — shunda ham ogohlantirish chiqishi kerak."""
    from core.logic.check_patterns import CheckCategory, add_pattern

    async with session_factory() as session:
        await set_shadow_mode(session, True)
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")

    value, said = await shadow_env("off")

    assert value is False
    assert "birorta ham shablon yo'q" in said[0]
    assert "CHECK_FAILED" in said[0]
    assert "CHECK_PASSED" not in said[0]  # bu kategoriya to'ldirilgan


async def test_k3_shadow_on_does_not_warn(shadow_env, session_factory):
    """Soya rejimini YOQISH xavfsiz amal — ogohlantirish o'rinsiz."""
    async with session_factory() as session:
        await set_shadow_mode(session, False)

    value, said = await shadow_env("on")

    assert value is True
    assert "shablon" not in said[0]
