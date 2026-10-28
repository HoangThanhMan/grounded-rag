"""The engine and the per-request session.

SQLite gets no connection pool: a pooled aiosqlite connection belongs to the
event loop that opened it, and the tests and the background indexer each run
their own loop. It also enforces foreign keys only when asked to, on every
connection - without that, deleting a conversation would leave its messages.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from grounded_rag.config import settings


def _engine():
    url = settings.database_url
    if not url.startswith("sqlite"):
        if settings.database_pool_size == 0:
            return create_async_engine(url, poolclass=NullPool)
        return create_async_engine(
            url, pool_size=settings.database_pool_size, pool_pre_ping=True
        )
    eng = create_async_engine(url, poolclass=NullPool)

    @event.listens_for(eng.sync_engine, "connect")
    def _foreign_keys(dbapi_conn, _record) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return eng


engine = _engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def ping_db() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
