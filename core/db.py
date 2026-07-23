"""Async SQLAlchemy engine va session boshqaruvi."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from core.models import Base

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    async with SessionLocal() as session:
        yield session


def sqlite_file_path(database_url: str) -> str | None:
    """`sqlite+aiosqlite:///path/to.db` dan xom fayl yo'lini ajratadi.

    SQLite bo'lmagan (masalan kelajakda PostgreSQL) DATABASE_URL uchun
    None qaytaradi — backup (MVP-4, Q60) faqat SQLite fayl nusxalashga
    tayyor, boshqa DB turlari uchun alohida yechim kerak bo'ladi.
    """
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    return database_url[len(prefix):]
