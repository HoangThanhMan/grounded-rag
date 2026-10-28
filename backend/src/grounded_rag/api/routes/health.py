"""Liveness and readiness, kept apart: a server that is up but cannot reach
its database should be taken out of rotation, not restarted."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from grounded_rag.db.session import ping_db
from grounded_rag.retrieval.store import get_store

router = APIRouter(tags=["health"])
log = logging.getLogger("grounded_rag.health")


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
    """"ok" or "unavailable": the reason goes to the log, not to whoever asks -
    it can name hosts and users."""
    try:
        await asyncio.wait_for(probe, timeout=3)
        return "ok"
    except Exception:
        log.exception("readiness check failed")
        return "unavailable"
