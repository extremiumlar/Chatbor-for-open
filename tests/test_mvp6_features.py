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

from core.enums import CaseStatus
from core.logic.case_search import search_cases
from core.logic.customers import case_count_for_user, cases_for_user, list_customers
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
    app.dependency_overrides[require_admin] = lambda: 777

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
