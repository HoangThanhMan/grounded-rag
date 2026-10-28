"""Tests run on the mock provider whatever .env says: no keys, no model
weights, no network. Qdrant tests use the embedded ':memory:' mode, the
database is a throwaway SQLite file.

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
    DATABASE_URL=f"sqlite+aiosqlite:///{_TMP / 'test.db'}",
    UPLOAD_DIR=str(_TMP / "uploads"),
    ADMIN_API_KEY="test",
    AUTO_SEED_DIR="",
    RATE_LIMIT_PER_MINUTE="0",
)

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

@pytest.fixture(scope="session", autouse=True)
def database():
    from grounded_rag.db.models import Base
    from grounded_rag.db.session import engine

    async def create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())
