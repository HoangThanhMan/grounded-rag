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
from grounded_rag.api.owner import OwnerCookie
from grounded_rag.api.routes import chat, conversations, documents, health
from grounded_rag.compute import run_model
from grounded_rag.config import settings
from grounded_rag.documents import (
    index_document,
    mark_missing,
    register_corpus,
    requeue_interrupted,
)
from grounded_rag.generation.llm_client import get_llm_client
from grounded_rag.observability import metrics
from grounded_rag.retrieval.search import warm_up

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# The access log is already JSON: one bare line each, for whatever ships the logs.
_access = logging.getLogger("grounded_rag.access")
_access_handler = logging.StreamHandler()
_access_handler.setFormatter(logging.Formatter("%(message)s"))
_access.addHandler(_access_handler)
_access.propagate = False
# one line per HTTP call to Qdrant, the LLM and the model hub is noise
for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("grounded_rag.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Before anything loads: the library lists the corpus, and a document the
    # index lacks - or that a restart caught mid-index - says so, not "ready",
    # while the models take minutes to arrive.
    pending: list[str] = []
    try:
        pending += await requeue_interrupted()
        pending += await mark_missing()
        if settings.auto_seed_dir:
            pending += await register_corpus(Path(settings.auto_seed_dir))
    except Exception:
        log.exception("could not compare the library with the index")
    pending = list(dict.fromkeys(pending))
    indexing = asyncio.create_task(_catch_up(pending))
    yield
    indexing.cancel()
    # the provider client keeps a connection pool open for the life of the app
    if close := getattr(get_llm_client(), "aclose", None):
        await close()


async def _catch_up(pending: list[str]) -> None:
    """After startup, in the background: load the models, then index what
    the library lists but the index lacks."""
    try:
        await run_model(warm_up)
    except Exception:
        # a broken model shows up on the first question too; not fatal here
        log.exception("warming the models up failed")
    for doc_id in pending:
        await index_document(doc_id)
    if pending:
        log.info("indexed %d document(s) at startup", len(pending))


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
        allow_credentials=True,     # the history cookie
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
app.add_middleware(OwnerCookie)
app.add_middleware(RequestContext)

if metrics.enabled():
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
