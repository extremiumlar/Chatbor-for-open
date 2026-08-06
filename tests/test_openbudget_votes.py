"""openbudget.uz ovozlarini o'qish va SQLite'ga yozish testlari.

Real sayt CAPTCHA bilan himoyalangani uchun tarmoq qatlami `httpx.MockTransport`
bilan almashtiriladi — testlar API MANTIQINI (sahifalash, idempotentlik,
410 -> token eskirgan) tekshiradi, saytning o'zini emas.
"""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.logic.openbudget import (
    OpenBudgetVotesClient,
    VoteTokenExpiredError,
    extract_last4,
    find_votes_by_last4,
    sync_votes,
)
from core.models import Base

INITIATIVE = "4b377184-72c0-4ab6-854f-a5d912cdf506"
PAGE_SIZE = 2
VOTES = [
    {"phoneNumber": "**** **** 12 34", "voteDate": "2026-03-01 10:15:00"},
    {"phoneNumber": "**** **** 56 78", "voteDate": "2026-03-01 11:20:00"},
    {"phoneNumber": "**** **** 12 34", "voteDate": "2026-03-02 09:05:00"},
]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _make_client(
    *, calls: list[int] | None = None, status: int = 200, expire_from_page: int | None = None
):
    """Saytning sahifalangan javobini taqlid qiluvchi klient.

    `expire_from_page` — shu sahifadan boshlab token eskirgandek (410)
    javob beradi; token o'rtada tugab qolishini modellashtiradi.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="gone")
        page = int(request.url.params.get("page", 0))
        if calls is not None:
            calls.append(page)
        if expire_from_page is not None and page >= expire_from_page:
            return httpx.Response(410, text="gone")
        chunk = VOTES[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        return httpx.Response(200, json={"content": chunk, "totalElements": len(VOTES)})

    transport = httpx.MockTransport(handler)
    return OpenBudgetVotesClient("token", client=httpx.AsyncClient(transport=transport))


@pytest.mark.parametrize(
    "masked,expected",
    [
        ("**** **** 12 34", "1234"),
        ("+998 ** *** 56 78", "5678"),
        ("****1234", "1234"),
        ("", None),
        ("****", None),
    ],
)
def test_extract_last4(masked, expected):
    assert extract_last4(masked) == expected


@pytest.mark.asyncio
async def test_sync_walks_all_pages_and_writes_rows(session):
    calls: list[int] = []
    async with _make_client(calls=calls) as client:
        inserted, seen = await sync_votes(
            session, client, INITIATIVE, page_delay_seconds=0
        )

    assert (inserted, seen) == (3, 3)
    assert calls == [0, 1]  # jami 3 ta yozuv, sahifa hajmi 2 -> ikki so'rov
    rows = await find_votes_by_last4(session, INITIATIVE, "1234")
    assert len(rows) == 2
    assert rows[0].voted_at is not None  # sana parse bo'ldi


@pytest.mark.asyncio
async def test_sync_is_idempotent(session):
    async with _make_client() as client:
        await sync_votes(session, client, INITIATIVE, page_delay_seconds=0)
    async with _make_client() as client:
        inserted, seen = await sync_votes(
            session, client, INITIATIVE, page_delay_seconds=0
        )

    assert inserted == 0  # ikkinchi yurishda dublikat yaratilmadi
    assert seen == 3
    assert len(await find_votes_by_last4(session, INITIATIVE, "1234")) == 2


@pytest.mark.asyncio
async def test_expired_token_raises(session):
    async with _make_client(status=410) as client:
        with pytest.raises(VoteTokenExpiredError):
            await sync_votes(session, client, INITIATIVE, page_delay_seconds=0)


@pytest.mark.asyncio
async def test_expiry_midway_keeps_progress_and_reports_page(session):
    """Token ikkinchi sahifada tugasa — birinchi sahifa bazada qolishi kerak."""
    async with _make_client(expire_from_page=1) as client:
        with pytest.raises(VoteTokenExpiredError) as exc_info:
            await sync_votes(session, client, INITIATIVE, page_delay_seconds=0)

    assert exc_info.value.page == 1  # yangi token bilan shu sahifadan davom etiladi
    rows = await find_votes_by_last4(session, INITIATIVE, "1234")
    assert len(rows) == 1  # 0-sahifadagi yagona "1234" saqlanib qolgan


@pytest.mark.asyncio
async def test_resume_from_start_page_completes_the_list(session):
    """Uzilgan sinxronizatsiya boshidan emas, uzilgan sahifadan davom etadi."""
    async with _make_client(expire_from_page=1) as client:
        with pytest.raises(VoteTokenExpiredError) as exc_info:
            await sync_votes(session, client, INITIATIVE, page_delay_seconds=0)

    calls: list[int] = []
    async with _make_client(calls=calls) as client:
        inserted, seen = await sync_votes(
            session,
            client,
            INITIATIVE,
            start_page=exc_info.value.page,
            page_delay_seconds=0,
        )

    # 0-sahifa qayta o'qilmadi. 2 — bo'sh sahifada to'xtash uchun ortiqcha
    # so'rov: davom ettirishda sahifa hajmi noma'lum (izohga qarang).
    assert calls == [1, 2]
    assert (inserted, seen) == (1, 1)
    assert len(await find_votes_by_last4(session, INITIATIVE, "1234")) == 2


@pytest.mark.asyncio
async def test_unknown_last4_returns_empty(session):
    async with _make_client() as client:
        await sync_votes(session, client, INITIATIVE, page_delay_seconds=0)
    assert await find_votes_by_last4(session, INITIATIVE, "0000") == []
