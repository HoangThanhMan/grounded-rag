from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from grounded_rag.api.routes_chat import CONFIG_DIR, load_config
from grounded_rag.api.schemas import ConfigSummary, IngestRequest, IngestResponse
from grounded_rag.config import settings
from grounded_rag.ingest.pipeline import ingest

router = APIRouter(tags=["admin"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "provider": settings.llm_provider}


@router.post("/ingest", response_model=IngestResponse)
def run_ingest(req: IngestRequest):
    # Plain `def`: embedding a corpus is CPU-bound, so FastAPI runs it in its
    # threadpool instead of blocking the event loop that serves /chat.
    return ingest(Path(req.source), load_config(req.config), recreate=req.recreate)


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
