"""MVP-6: Web panel — Telegram Login Widget hash tekshiruvi (tarmoqsiz, sof
funksiya), murojaat/mijoz qidiruv-filtr mantig'i, va FastAPI route'lari
(izolyatsiyalangan test bazasi + soxta autentifikatsiya bilan).

Haqiqiy Telegram redirect BU YERDA SINALMAYDI (bu muhitda real HTTPS domen
yo'q) — faqat hash-tekshiruv algoritmi va route'larning DB-mantig'i.
"""

import datetime
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.case_search import search_cases
from core.logic.customers import case_count_for_user, cases_for_user, list_customers
from core.models import Admin, AdminRole
from panel_service.auth import verify_telegram_auth

BOT_TOKEN = "123456:test-bot-token"


def _sign(data: dict, bot_token: str) -> dict:
    payload = dict(data)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return payload


# --------------------------------------------------------------------------- #
# Telegram Login Widget hash tekshiruvi
# --------------------------------------------------------------------------- #


def test_verify_telegram_auth_accepts_valid_signature():
    data = {"id": 12345, "first_name": "Test", "auth_date": 1_000_000}
    signed = _sign(data, BOT_TOKEN)
    assert verify_telegram_auth(signed, BOT_TOKEN, now=1_000_010) is True


def test_verify_telegram_auth_rejects_tampered_field():
    data = {"id": 12345, "first_name": "Test", "auth_date": 1_000_000}
    signed = _sign(data, BOT_TOKEN)
    signed["first_name"] = "Hacker"  # imzolangandan keyin o'zgartirildi
    assert verify_telegram_auth(signed, BOT_TOKEN, now=1_000_010) is False


def test_verify_telegram_auth_rejects_wrong_bot_token():
    data = {"id": 12345, "first_name": "Test", "auth_date": 1_000_000}
    signed = _sign(data, BOT_TOKEN)
    assert verify_telegram_auth(signed, "different:token", now=1_000_010) is False


def test_verify_telegram_auth_rejects_stale_auth_date():
    data = {"id": 12345, "first_name": "Test", "auth_date": 1_000_000}
    signed = _sign(data, BOT_TOKEN)
    # 90000 soniya o'tgan, standart max_age 86400 dan katta.
    assert verify_telegram_auth(signed, BOT_TOKEN, max_age_seconds=86400, now=1_000_000 + 90_000) is False


def test_verify_telegram_auth_rejects_missing_hash():
    assert verify_telegram_auth({"id": 1, "auth_date": 1}, BOT_TOKEN) is False


# --------------------------------------------------------------------------- #
# Murojaat qidiruv/filtr (TZ 11.6)
# --------------------------------------------------------------------------- #


async def test_search_cases_filters_by_phone_and_status(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(601, "u1", "U1", "998901111111")
    await cm.handle_coupon_received(601, "111111")  # CONFIRMED

    await cm.handle_phone_detected(602, "u2", "U2", "998902222222")
    await cm.handle_coupon_received(602, "333333")  # REJECTED

    async with session_factory() as session:
        by_phone = await search_cases(session, phone="998901")
        assert len(by_phone) == 1
        assert by_phone[0].phone == "998901111111"

        by_status = await search_cases(session, status=CaseStatus.REJECTED)
        assert len(by_status) == 1
        assert by_status[0].phone == "998902222222"

        assert await search_cases(session, phone="000000000000") == []


async def test_search_cases_filters_by_date_range(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(603, "u3", "U3", "998903333333")

    async with session_factory() as session:
        assert await search_cases(session, date_from=datetime.date(2099, 1, 1)) == []
        assert len(await search_cases(session, date_to=datetime.date(2099, 1, 1))) == 1


# --------------------------------------------------------------------------- #
# Mijozlar — CRM ko'rinishi (TZ 11.6)
# --------------------------------------------------------------------------- #


async def test_list_customers_search_and_history(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(701, "findme_user", "Find Me", "998904444444")

    async with session_factory() as session:
        found = await list_customers(session, search="findme")
        assert len(found) == 1
        user = found[0]
        assert user.tg_username == "findme_user"

        cases = await cases_for_user(session, user.id)
        assert len(cases) == 1
        assert cases[0].phone == "998904444444"

        assert await case_count_for_user(session, user.id) == 1


async def test_list_customers_and_search_cases_scoped_by_assigned_admin(
    seed_bots, make_case_manager, session_factory
):
    """Audit K-4 (TZ 11.0, Q51) — oddiy admin panel qidiruvida ham faqat
    o'ziga biriktirilgan (yoki hali biriktirilmagan) mijoz/case'larni
    ko'rishi kerak."""
    from core.logic.case_admin import assign_customer
    from core.models import User

    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()
    await cm.handle_phone_detected(710, "mine", "Mine", "998907000001")
    await cm.handle_phone_detected(711, "theirs", "Theirs", "998907000002")

    async with session_factory() as session:
        mine_user = (await session.execute(select(User).where(User.tg_user_id == 710))).scalars().first()
        theirs_user = (
            await session.execute(select(User).where(User.tg_user_id == 711))
        ).scalars().first()
        await assign_customer(session, mine_user.id, 50)
        await assign_customer(session, theirs_user.id, 60)

        visible_customers = await list_customers(session, viewer_admin_id=50, can_see_all=False)
        assert {u.tg_username for u in visible_customers} == {"mine"}

        visible_cases = await search_cases(session, viewer_admin_id=50, can_see_all=False)
        assert {c.phone for c in visible_cases} == {"998907000001"}

        # Owner/Rop (can_see_all=True) — hammasini ko'radi.
        assert len(await list_customers(session, can_see_all=True)) == 2
        assert len(await search_cases(session, can_see_all=True)) == 2


# --------------------------------------------------------------------------- #
# FastAPI route'lari — izolyatsiyalangan test bazasi bilan
# --------------------------------------------------------------------------- #


@pytest.fixture
def panel_client(seed_bots, make_case_manager, session_factory):
    from panel_service.app import app, get_db, require_admin

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    # Audit K-4 — require_admin endi `Admin` qatorining o'zini qaytaradi
    # (bool/int emas), rol-asoslangan ko'rish-cheklash uchun. Testda
    # cheklovsiz (OWNER) admin sifatida kirilyapti — mavjud
    # cases/customers hech kimga biriktirilmagan bo'lgani uchun bu
    # rolidan qat'i nazar ham ko'rinardi, lekin haqiqiy interfeysga mos
    # bo'lishi uchun to'liq Admin obyekti beriladi.
    app.dependency_overrides[require_admin] = lambda: Admin(
        id=777, tg_user_id=777, name="test-owner", role=AdminRole.OWNER
    )

    client = TestClient(app, follow_redirects=False)
    yield client

    app.dependency_overrides.clear()


async def test_authenticated_routes_return_200(panel_client, seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(801, "webuser", "Web User", "998905555555")
    await cm.handle_coupon_received(801, "111111")

    async with session_factory() as session:
        from core.models import Case

        case = (await session.execute(Case.__table__.select())).first()
        case_id = case.id
        from core.models import User

        user = (await session.execute(User.__table__.select())).first()
        user_id = user.id

    for path in ("/", "/audit", "/cases", f"/cases/{case_id}", "/customers", f"/customers/{user_id}"):
        response = panel_client.get(path)
        assert response.status_code == 200, path


async def test_restricted_admin_panel_hides_other_admins_customer(
    seed_bots, make_case_manager, session_factory
):
    """Audit K-4 (TZ 11.0, Q51) — oddiy (OWNER/ROP bo'lmagan) admin panel
    orqali boshqa adminga biriktirilgan mijozni ko'ra olmasligi kerak."""
    from panel_service.app import app, get_db, require_admin
    from core.logic.case_admin import assign_customer
    from core.models import User

    await seed_bots(["bot1"])
    cm = make_case_manager()
    await cm.handle_phone_detected(802, "restricted_target", "Target", "998906666666")

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == 802))
        ).scalars().first()
        await assign_customer(session, user.id, 999)  # boshqa adminga biriktirildi
        user_id = user.id

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = lambda: Admin(
        id=42, tg_user_id=42, name="plain-admin", role=AdminRole.ADMIN
    )
    client = TestClient(app, follow_redirects=False)
    try:
        assert client.get(f"/customers/{user_id}").status_code == 404
        body = client.get("/customers").text
        assert "restricted_target" not in body
    finally:
        app.dependency_overrides.clear()


async def test_removed_admin_session_is_rejected(session_factory):
    """Audit O-4 (TZ 12.2) — avval `require_admin` faqat sessiya
    (`tg_user_id`) borligini tekshirardi; admin `admins` jadvalidan olib
    tashlansa ham eski sessiya orqali panelga kirish davom etardi. Endi
    `require_admin` har so'rovda `admins` jadvalini qayta tekshiradi."""
    from panel_service.app import NotAuthenticated, require_admin
    from core.logic.admins import ensure_admins_seeded, get_admin_by_tg_id

    class _FakeRequest:
        def __init__(self, tg_user_id):
            self.session = {"tg_user_id": tg_user_id}  # dict'ning .get()/.clear() yetarli

    async with session_factory() as session:
        await ensure_admins_seeded(session, [808])
        admin = await get_admin_by_tg_id(session, 808)
        assert admin is not None

    async with session_factory() as session:
        req = _FakeRequest(808)
        # Hali admin ro'yxatda — sessiya qabul qilinadi.
        result = await require_admin(req, db=session)
        assert result.tg_user_id == 808

    async with session_factory() as session:
        admin = await get_admin_by_tg_id(session, 808)
        await session.delete(admin)
        await session.commit()

    async with session_factory() as session:
        req = _FakeRequest(808)  # sessiyada hamon "808" bor (eski)
        try:
            await require_admin(req, db=session)
            assert False, "NotAuthenticated kutilgan edi"
        except NotAuthenticated:
            pass
        assert "tg_user_id" not in req.session  # sessiya tozalangan


def test_unauthenticated_request_redirects_to_login():
    from panel_service.app import app

    app.dependency_overrides.clear()
    client = TestClient(app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_case_detail_404_for_missing_case(panel_client):
    response = panel_client.get("/cases/999999")
    assert response.status_code == 404
