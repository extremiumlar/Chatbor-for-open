"""Statistika bo'limi kengaytmasi: nol-faoliyatli hodimlar ko'rinishi,
oldingi davr bilan solishtirish, reyting, OWNER o'z-o'zini tiklash."""

import datetime

from sqlalchemy import select

from core.logic.admins import ensure_admins_seeded, ensure_owner_exists
from core.logic.v2_stats import (
    AdminStatRow,
    StatsReport,
    gather_v2_stats,
    gather_with_comparison,
    leaderboard,
    render_admin_detail,
    render_leaderboard,
    trend,
)
from core.models import Admin, AdminRole


# --------------------------------------------------------------------------- #
# OWNER o'z-o'zini tiklash (qulflanish tuzatmasi)
# --------------------------------------------------------------------------- #


async def test_seeding_creates_owner_for_first_admin(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        admins = (await session.execute(select(Admin).order_by(Admin.id))).scalars().all()
    assert admins[0].role == AdminRole.OWNER
    assert admins[1].role == AdminRole.ADMIN


async def test_owner_lockout_is_self_healed(session_factory):
    """Yagona OWNER boshqa rolga tushirilsa — keyingi ishga tushishda
    ADMIN_TG_IDS'ning birinchisi OWNER'ga qaytariladi. Aks holda /setrole
    (faqat OWNER'niki) ni hech kim ishlata olmay, tizim qulflanadi."""
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        first = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 111))
        ).scalars().first()
        first.role = AdminRole.DASTURCHI  # OWNER yo'qoldi
        await session.commit()

        promoted = await ensure_owner_exists(session, [111, 222])
        assert promoted is not None
        assert promoted.tg_user_id == 111
        assert promoted.role == AdminRole.OWNER


async def test_owner_heal_noop_when_owner_alive(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        assert await ensure_owner_exists(session, [111]) is None  # allaqachon bor


# --------------------------------------------------------------------------- #
# T-11 — avtomatik ko'tarilish KO'RINADIGAN bo'lsin
# --------------------------------------------------------------------------- #


async def test_t11_auto_promotion_is_written_to_the_audit_log(session_factory):
    """Jonli sinovda foydalanuvchi o'zini DASTURCHI qildi, restartdan keyin
    rol jimgina OWNER'ga qaytdi va u buni bilmadi. Mexanizm to'g'ri —
    ko'rinmasligi muammo edi."""
    from core.logic.audit import list_recent

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        first = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 111))
        ).scalars().first()
        first.role = AdminRole.DASTURCHI
        await session.commit()

        await ensure_owner_exists(session, [111, 222])
        entries = await list_recent(session)

    promo = [e for e in entries if e.action == "auto_promote_owner"]
    assert len(promo) == 1, "ko'tarilish audit jurnaliga tushmadi"
    assert promo[0].admin_tg_id == 111
    # Qaysi roldan ko'tarilgani ham yozilsin — "nima o'zgardi" savoliga javob.
    assert "DASTURCHI" in promo[0].details
    assert "OWNER" in promo[0].details


async def test_t11_no_audit_entry_when_owner_already_exists(session_factory):
    """Har ishga tushishda bekorga yozuv qo'shilmasin — aks holda audit
    jurnali shovqinga to'lib, haqiqiy hodisalar ko'rinmay qoladi."""
    from core.logic.audit import list_recent

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        await ensure_owner_exists(session, [111])
        await ensure_owner_exists(session, [111])
        entries = await list_recent(session)

    assert [e for e in entries if e.action == "auto_promote_owner"] == []


async def test_t11_is_last_active_owner(session_factory):
    """`/setrole` ogohlantirishi shu tekshiruvga tayanadi."""
    from core.logic.admins import get_admin_by_tg_id, is_last_active_owner, set_admin_role

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        owner = await get_admin_by_tg_id(session, 111)
        other = await get_admin_by_tg_id(session, 222)

        assert await is_last_active_owner(session, owner.id) is True
        assert await is_last_active_owner(session, other.id) is False

        # Ikkinchi Owner paydo bo'lsa — endi hech kim "yagona" emas.
        await set_admin_role(session, other.id, AdminRole.OWNER)
        assert await is_last_active_owner(session, owner.id) is False
        assert await is_last_active_owner(session, other.id) is False


async def test_t11_setrole_warns_before_demoting_the_last_owner(
    session_factory, monkeypatch
):
    """Ogohlantirish AMALDA chiqishi kerak — buyruq haqiqiy router orqali."""
    import datetime as _dt

    from aiogram.types import Chat, Message, User as TgUser

    import adminbot_service.bot as ab

    said: list[str] = []

    async def fake_answer(self, text="", **kw):
        said.append(text)

    monkeypatch.setattr(ab, "get_session", session_factory)
    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])

    def _msg(text: str) -> Message:
        return Message(
            message_id=1,
            date=_dt.datetime.now(),
            chat=Chat(id=1, type="private"),
            from_user=TgUser(id=111, is_bot=False, first_name="Owner"),
            text=text,
        )

    # Yagona Owner o'zini pasaytiryapti — ogohlantirish shart.
    await ab.admin_router.propagate_event(
        "message", _msg("/setrole 111 DASTURCHI"), bot=None, event_update=None
    )
    assert "YAGONA faol Owner" in said[-1], said

    # Oddiy adminning rolini o'zgartirish — ogohlantirish kerak emas.
    async with session_factory() as session:
        await ensure_owner_exists(session, [111])  # Owner'ni qaytaramiz
    await ab.admin_router.propagate_event(
        "message", _msg("/setrole 222 KUZATUVCHI"), bot=None, event_update=None
    )
    assert "YAGONA faol Owner" not in said[-1], said


async def test_t11_setrole_rejects_non_numeric_id(session_factory, monkeypatch):
    """Raqam bo'lmagan id handler'ni yiqitmasligi kerak (avval `int()`
    xatosi bilan yiqilardi va foydalanuvchiga hech narsa qaytmasdi)."""
    import datetime as _dt

    from aiogram.types import Chat, Message, User as TgUser

    import adminbot_service.bot as ab

    said: list[str] = []

    async def fake_answer(self, text="", **kw):
        said.append(text)

    monkeypatch.setattr(ab, "get_session", session_factory)
    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])

    msg = Message(
        message_id=1,
        date=_dt.datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=TgUser(id=111, is_bot=False, first_name="Owner"),
        text="/setrole @kimdir ADMIN",
    )
    await ab.admin_router.propagate_event("message", msg, bot=None, event_update=None)

    assert said and "raqam bo'lishi kerak" in said[-1]


# --------------------------------------------------------------------------- #
# Nol-faoliyatli hodimlar ham ro'yxatda ko'rinadi
# --------------------------------------------------------------------------- #


async def test_idle_admins_appear_in_report(session_factory):
    """Hech narsa qilmagan hodim ro'yxatdan tushib qolmasligi kerak —
    "bugun umuman ishlamadi" ma'lumoti boshliq uchun signal."""
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222, 333])
        since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        report = await gather_v2_stats(session, since)

    # Ism/username hali ma'lum emas (admin bot bilan hali gaplashmagan) —
    # shunda ham "kim" ekani ko'rinishi uchun `id:<tg_id>` ko'rsatiladi,
    # xom raqam emas (raqamning o'zi ro'yxatda nimani anglatishi noaniq).
    names = {r.admin_name for r in report.rows if r.admin_id is not None}
    assert names == {"id:111", "id:222", "id:333"}
    assert all(r.cases == 0 for r in report.rows)


async def test_inactive_admins_are_not_padded_in(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        second = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 222))
        ).scalars().first()
        second.is_active = False
        await session.commit()

        since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        report = await gather_v2_stats(session, since)

    names = {r.admin_name for r in report.rows if r.admin_id is not None}
    assert names == {"id:111"}  # nofaol hodim ro'yxatga qo'shilmaydi


async def test_admin_filter_pads_only_that_admin(session_factory):
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        target = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 222))
        ).scalars().first()
        since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        report = await gather_v2_stats(session, since, admin_id=target.id)

    ids = {r.admin_id for r in report.rows}
    assert ids == {target.id}


# --------------------------------------------------------------------------- #
# Solishtirish (trend) va reyting
# --------------------------------------------------------------------------- #


def test_trend_formatting():
    assert trend(10, 5) == "↗️ +100%"
    assert trend(5, 10) == "↘️ -50%"
    assert trend(7, 7) == "→ 0%"
    assert trend(3, 0) == "🆕"
    assert trend(0, 0) == "—"


async def test_comparison_windows_do_not_overlap(session_factory):
    """Oldingi davr so'rovi joriy davr hodisalarini qamrab olmasligi kerak."""
    async with session_factory() as session:
        await ensure_admins_seeded(session, [111])
        since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        cmp = await gather_with_comparison(session, since)

    assert cmp.previous.since_utc < cmp.current.since_utc
    # previous oynasi aynan current boshlanishida tugaydi (until_utc=since).


def _row(name, passed=0, cases=0, conv_checked=0, admin_id=1):
    r = AdminStatRow(admin_id=admin_id, admin_name=name)
    r.passed = passed
    r.cases = cases
    r.failed = conv_checked - passed if conv_checked else 0
    return r


def test_leaderboard_orders_by_passed_then_conversion():
    rows = [
        _row("past", passed=1, cases=10, conv_checked=5, admin_id=1),
        _row("top", passed=8, cases=9, conv_checked=10, admin_id=2),
        _row("mid", passed=8, cases=9, conv_checked=16, admin_id=3),  # conv 50%
        AdminStatRow(admin_id=None, admin_name="biriktirilmagan"),  # reytingdan tashqari
    ]
    report = StatsReport(
        since_utc=datetime.datetime.utcnow(), rows=rows, totals=AdminStatRow(None, "Jami")
    )
    ordered = leaderboard(report)
    assert [r.admin_name for r in ordered] == ["top", "mid", "past"]
    assert all(r.admin_id is not None for r in ordered)


def test_render_leaderboard_marks_idle_admins():
    rows = [
        _row("ishchan", passed=3, cases=4, conv_checked=4, admin_id=1),
        _row("dam olgan", admin_id=2),
    ]
    report = StatsReport(
        since_utc=datetime.datetime.utcnow(), rows=rows, totals=AdminStatRow(None, "Jami")
    )
    text = render_leaderboard(report, "Sinov")
    assert "🥇" in text and "ishchan" in text
    assert "💤" in text and "dam olgan" in text


def test_render_admin_detail_shows_trend_and_idle_note():
    cur = _row("hodim", passed=4, cases=6, conv_checked=5)
    prev = _row("hodim", passed=2, cases=3, conv_checked=3)
    text = render_admin_detail(cur, prev, "Hafta")
    assert "↗️ +100%" in text  # passed 2 -> 4

    idle = _row("bo'sh hodim")
    text2 = render_admin_detail(idle, None, "Bugun")
    assert "faoliyat qayd etilmagan" in text2


# --------------------------------------------------------------------------- #
# vst callback'lari ruxsat matritsasida
# --------------------------------------------------------------------------- #


def test_stats_callbacks_open_to_all_roles():
    """Statistika tugmalari hamma rolga ochiq — cheklov ko'rsatish qatlamida
    (oddiy admin baribir faqat o'zinikini oladi)."""
    from core.logic import permissions as perms

    for role in AdminRole:
        a = Admin(id=1, tg_user_id=1, name="x", role=role, is_active=True)
        for data in ("vst:d", "vst:w:h", "vst:d:c:5"):
            assert perms.can_use_callback(a, data), (role, data)


def test_v2_action_callbacks_are_restricted():
    from core.logic import permissions as perms

    viewer = Admin(id=1, tg_user_id=1, name="x", role=AdminRole.KUZATUVCHI, is_active=True)
    operator = Admin(id=2, tg_user_id=2, name="y", role=AdminRole.ADMIN, is_active=True)

    assert perms.can_use_callback(viewer, "vres:1:send") is False
    assert perms.can_use_callback(operator, "vres:1:send") is True
    assert perms.can_use_callback(operator, "ucp:1:add") is False  # faqat Owner/Rop


# --------------------------------------------------------------------------- #
# "Kim kimligi" — adminlar ro'yxatida raqam emas, ism ko'rinishi kerak
# --------------------------------------------------------------------------- #


def test_display_name_prefers_full_name_and_username():
    from core.logic.admins import display_name

    a = Admin(id=1, tg_user_id=555, name="555", role=AdminRole.ADMIN, is_active=True)

    # Hech narsa ma'lum emas — hech bo'lmasa raqam ekani bilinsin.
    assert display_name(a) == "id:555"

    a.tg_username = "aliyev"
    assert display_name(a) == "@aliyev"

    a.full_name = "Ali Valiyev"
    assert display_name(a) == "Ali Valiyev (@aliyev)"

    a.tg_username = None
    assert display_name(a) == "Ali Valiyev"


async def test_refresh_admin_identity_updates_and_is_idempotent(session_factory):
    """Admin bot bilan gaplashganda ismi o'z-o'zidan yozilishi kerak —
    qo'lda kiritish talab qilinmasin."""
    from core.logic.admins import display_name, refresh_admin_identity

    async with session_factory() as session:
        await ensure_admins_seeded(session, [777])
        admin = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 777))
        ).scalars().first()

        assert display_name(admin) == "id:777"

        changed = await refresh_admin_identity(session, admin, "Bek Bekov", "bekov")
        assert changed is True
        assert display_name(admin) == "Bek Bekov (@bekov)"
        # Seed paytidagi xom raqamli `name` ham tushunarli nomga almashadi.
        assert admin.name == "Bek Bekov"

        # Ikkinchi marta o'zgarish yo'q — ortiqcha yozuv qilinmasligi kerak.
        assert await refresh_admin_identity(session, admin, "Bek Bekov", "bekov") is False

        # Username o'zgarsa — yangilanadi.
        assert await refresh_admin_identity(session, admin, "Bek Bekov", "yangi") is True
        assert admin.tg_username == "yangi"


async def test_stats_report_uses_readable_admin_names(session_factory):
    """Hisobotda ham raqam emas, ism ko'rinishi kerak."""
    from core.logic.admins import refresh_admin_identity

    async with session_factory() as session:
        await ensure_admins_seeded(session, [888])
        admin = (
            await session.execute(select(Admin).where(Admin.tg_user_id == 888))
        ).scalars().first()
        await refresh_admin_identity(session, admin, "Dilnoza", "dilnoza")

        since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        report = await gather_v2_stats(session, since)

    names = {r.admin_name for r in report.rows if r.admin_id is not None}
    assert names == {"Dilnoza (@dilnoza)"}


# --------------------------------------------------------------------------- #
# T-7 — eski `/stats` ekrani ham §8.4 ko'rish cheklovini hurmat qilsin
#
# Jonli sinovda ADMIN rolidagi akkaunt bu ekranda boshqa adminning
# case'larini ham sanoqda ko'rgan edi (`/vstats` va `/problems` to'g'ri
# ishlardi, faqat shu eski ekran ochiq qolgan edi).
# --------------------------------------------------------------------------- #


async def _two_admins_two_customers(session_factory):
    """Ikki admin, har biriga biriktirilgan mijoz + biriktirilmagan mijoz."""
    from core.enums import CaseStatus
    from core.models import Case, User

    async with session_factory() as session:
        await ensure_admins_seeded(session, [111, 222])
        a1 = (await session.execute(select(Admin).where(Admin.tg_user_id == 111))).scalars().first()
        a2 = (await session.execute(select(Admin).where(Admin.tg_user_id == 222))).scalars().first()

        mine = User(tg_user_id=1001, assigned_admin_id=a1.id)
        theirs = User(tg_user_id=1002, assigned_admin_id=a2.id)
        nobodys = User(tg_user_id=1003, assigned_admin_id=None)
        session.add_all([mine, theirs, nobodys])
        await session.commit()

        session.add_all([
            Case(user_id=mine.id, phone="998900000001", status=CaseStatus.CONFIRMED),
            Case(user_id=theirs.id, phone="998900000002", status=CaseStatus.CONFIRMED),
            Case(user_id=nobodys.id, phone="998900000003", status=CaseStatus.CONFIRMED),
        ])
        await session.commit()
    return a1, a2


async def test_t7_ordinary_admin_sees_only_own_and_unassigned(session_factory):
    from core.logic.stats import gather_stats

    a1, _ = await _two_admins_two_customers(session_factory)

    async with session_factory() as session:
        limited = await gather_stats(session, viewer_admin_id=a1.id, can_see_all=False)
        everything = await gather_stats(session, can_see_all=True)

    # O'ziniki + biriktirilmagan = 2; boshqa adminning case'i ko'rinmasin.
    assert limited.today_count == 2
    assert limited.by_status.get("CONFIRMED") == 2
    # Owner/Rop hammasini ko'radi.
    assert everything.today_count == 3
    assert everything.by_status.get("CONFIRMED") == 3


async def test_t7_default_call_still_returns_everything(session_factory):
    """Eski chaqiruvlar (parametrsiz) buzilmasligi kerak."""
    from core.logic.stats import gather_stats

    await _two_admins_two_customers(session_factory)
    async with session_factory() as session:
        stats = await gather_stats(session)
    assert stats.today_count == 3


def test_t7_stats_text_marks_limited_view():
    from adminbot_service.views import stats_text
    from core.logic.stats import Stats

    s = Stats(today_count=1, by_status={}, problem_count=0)
    assert "faqat sizniki" in stats_text(s, own_only=True)
    assert "faqat sizniki" not in stats_text(s, own_only=False)
    # Eskirgan "bitta Teleton akkaunti" izohi olib tashlanganini tekshiramiz.
    assert "bitta Teleton akkaunti" not in stats_text(s)
