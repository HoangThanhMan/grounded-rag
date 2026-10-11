"""FastAPI entrypoint.

    uvicorn grounded_rag.api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from grounded_rag.api import routes_admin, routes_chat
from grounded_rag.generation.llm_client import LLMUnavailable, get_llm_client
from grounded_rag.observability import metrics

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # the provider client keeps a connection pool open for the life of the app
    if close := getattr(get_llm_client(), "aclose", None):
        await close()


app = FastAPI(
    title="grounded-rag",
    version="0.2.0",
    description="A RAG API that verifies every generated claim against its cited source.",
    lifespan=lifespan,
)
app.include_router(routes_admin.router)
app.include_router(routes_chat.router)


@app.exception_handler(LLMUnavailable)
async def llm_unavailable(request: Request, exc: LLMUnavailable) -> JSONResponse:
    # Refusing to answer is a 200. Failing to reach the model is not.
    return JSONResponse(status_code=503, content={"detail": f"LLM provider unavailable: {exc}"})


# The demo UI. Served by the API itself so there is one process, one origin
# and no CORS: `make run` and the browser has everything.
WEB_DIR = Path(__file__).resolve().parents[3] / "app" / "web"
if not WEB_DIR.is_dir():                      # installed without the repo layout
    WEB_DIR = Path("app/web")

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")


if metrics.enabled():
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
