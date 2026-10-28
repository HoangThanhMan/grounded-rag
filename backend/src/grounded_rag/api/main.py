"""FastAPI entrypoint.

    uvicorn grounded_rag.api.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from grounded_rag.api import errors
from grounded_rag.api.middleware import RequestContext
from grounded_rag.api.routes import chat, conversations, documents, health
from grounded_rag.config import settings
from grounded_rag.documents import fail_stale_processing, seed_corpus
from grounded_rag.generation.llm_client import get_llm_client
from grounded_rag.observability import metrics

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grounded_rag.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    stale = await fail_stale_processing()
    if stale:
        log.warning("%d document(s) were mid-index at the last shutdown, marked failed", stale)
    seeding = None
    if settings.auto_seed_dir:
        seeding = asyncio.create_task(seed_corpus(Path(settings.auto_seed_dir)))
    yield
    if seeding is not None:
        seeding.cancel()
    # the provider client keeps a connection pool open for the life of the app
    if close := getattr(get_llm_client(), "aclose", None):
        await close()


app = FastAPI(
    title="grounded-rag",
    version="1.0.0",
    description="Vietnamese legal Q&A that cites the clause behind every answer.",
    lifespan=lifespan,
)
errors.install(app)
for module in (chat, conversations, documents, health):
    app.include_router(module.router)

# Not needed behind nginx or the Vite dev proxy, where the UI and the API
# share an origin; only for a UI served from somewhere else.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
app.add_middleware(RequestContext)

if metrics.enabled():
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
