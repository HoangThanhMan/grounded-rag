"""Liveness and readiness, kept apart: a server that is up but cannot reach
its database should be taken out of rotation, not restarted."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from grounded_rag.db.session import ping_db
from grounded_rag.retrieval.store import get_store

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    checks = {"qdrant": _check(asyncio.to_thread(get_store().ping)), "db": _check(ping_db())}
    results = dict(zip(checks, await asyncio.gather(*checks.values()), strict=True))
    ok = all(v == "ok" for v in results.values())
    return JSONResponse(status_code=200 if ok else 503, content=results)


async def _check(probe) -> str:
    try:
        await asyncio.wait_for(probe, timeout=3)
        return "ok"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
