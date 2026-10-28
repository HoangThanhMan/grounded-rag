"""Tests run on the mock provider whatever .env says: no keys, no model
weights, no network. Qdrant tests use the embedded ':memory:' mode, the
database is a throwaway SQLite file - or, with TEST_DATABASE_URL set, a
Postgres database that is wiped and built by the Alembic migrations (CI does
this: SQLite ignores column lengths that Postgres enforces).

Set before anything imports grounded_rag.config, which reads the environment
once at import time.

Every process - the API, the CLI, the eval - runs from the repository root,
where `data/` lives. The tests do too, wherever pytest was started from."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="grounded-rag-test-"))
os.environ.update(
    LLM_PROVIDER="mock",
    QDRANT_URL=":memory:",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL")
    or f"sqlite+aiosqlite:///{_TMP / 'test.db'}",
    UPLOAD_DIR=str(_TMP / "uploads"),
    ADMIN_API_KEY="test",
    AUTO_SEED_DIR="",
    RATE_LIMIT_PER_MINUTE="0",
    # TestClient runs each request on an event loop of its own
    DATABASE_POOL_SIZE="0",
)

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

@pytest.fixture(scope="session", autouse=True)
def database():
    from grounded_rag.db.models import Base
    from grounded_rag.db.session import engine

    if not os.environ.get("TEST_DATABASE_URL"):
        async def create() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(create())
        return

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    async def wipe() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(wipe())
    command.upgrade(Config(str(REPO / "backend" / "alembic.ini")), "head")
