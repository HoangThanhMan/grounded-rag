from __future__ import annotations

import hmac
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from grounded_rag.api.routes_chat import CONFIG_DIR, load_config
from grounded_rag.api.schemas import ConfigSummary, IngestRequest, IngestResponse
from grounded_rag.compute import run_model
from grounded_rag.config import settings
from grounded_rag.ingest.pipeline import ingest

router = APIRouter(tags=["admin"])


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Off unless ADMIN_API_KEY is set, so a server nobody configured for it
    never reads files on request. The comparison is constant-time."""
    expected = settings.admin_api_key
    if not expected:
        raise HTTPException(403, "ingest over HTTP is disabled: set ADMIN_API_KEY or use the CLI")
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "missing or wrong X-API-Key", {"WWW-Authenticate": "ApiKey"})


def corpus_dir(source: str) -> Path:
    """The directory to ingest, refused unless it lies under data_root. Both
    sides are resolved first, so neither `..` nor a symlink leads out."""
    root = settings.data_root.resolve()
    path = Path(source).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(400, f"source must be a directory under {settings.data_root}/")
    if not path.is_dir():
        raise HTTPException(400, f"not a directory: {source}")
    return path


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "provider": settings.llm_provider}


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_admin)])
async def run_ingest(req: IngestRequest):
    """Adds to the index, never drops it: `--recreate` exists on the CLI only.
    Embedding is CPU-bound, so it queues on the same pool as the queries."""
    return await run_model(ingest, corpus_dir(req.source), load_config(req.config))


@router.get("/configs", response_model=list[ConfigSummary])
async def list_configs():
    """What the demo UI needs to describe each configuration without hardcoding
    it: which defences are on, and the guard threshold the entailment gauge is
    drawn against."""
    out = []
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        cfg = load_config(path.stem)
        out.append(
            ConfigSummary(
                name=cfg.name,
                guard_enabled=cfg.guard.enabled,
                entailment_threshold=cfg.guard.entailment_threshold,
                corrective_enabled=cfg.corrective.enabled,
                min_score=cfg.retrieval.min_score,
                chunker=cfg.retrieval.chunker,
            )
        )
    return out
