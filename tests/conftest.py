import asyncio
from contextlib import asynccontextmanager

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.logic.bot_pool import ensure_bots_seeded
from core.logic.case_manager import CaseManager
from core.models import Base
from teleton_service.mock_bot import MockVerificationBot


async def _default_alert(message: str, important: bool = True) -> None:
    pass


@pytest_asyncio.fixture
async def session_factory():
    """Har bir test uchun alohida, xotiradagi (in-memory) SQLite baza."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def factory():
        async with session_maker() as session:
            yield session

    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_bots(session_factory):
    async def _seed(usernames: list[str]) -> None:
        async with session_factory() as session:
            await ensure_bots_seeded(session, usernames)

    return _seed


@pytest_asyncio.fixture
async def make_case_manager(session_factory):
    """CaseManager instansiyalarini yasovchi factory, testdan keyin osilib
    qolgan mijoz-timeout tasklarini tozalaydi."""
    managers: list[CaseManager] = []

    def _make(
        bot_client=None,
        alert_sink=None,
        notify_customer=None,
        customer_timeout_seconds: float = 9999,
        suspicious_alert_sink=None,
        image_warning_sink=None,
        bot_response_max_retries: int = 3,
        bot_response_backoff_seconds: float = 0,
    ) -> CaseManager:
        kwargs = {}
        if suspicious_alert_sink is not None:
            kwargs["suspicious_alert_sink"] = suspicious_alert_sink
        if image_warning_sink is not None:
            kwargs["image_warning_sink"] = image_warning_sink

        manager = CaseManager(
            session_factory=session_factory,
            bot_client=bot_client or MockVerificationBot(),
            alert_sink=alert_sink or _default_alert,
            notify_customer=notify_customer,
            customer_timeout_seconds=customer_timeout_seconds,
            bot_response_max_retries=bot_response_max_retries,
            bot_response_backoff_seconds=bot_response_backoff_seconds,
            **kwargs,
        )
        managers.append(manager)
        return manager

    yield _make

    for manager in managers:
        for task in list(manager._customer_timers.values()):
            task.cancel()
        await asyncio.sleep(0)
