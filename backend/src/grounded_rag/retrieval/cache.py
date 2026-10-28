"""A disk cache for search(), for evaluation runs only.

Four configurations over 240 questions rerank the same queries again and again,
and reranking is most of the CPU time. With RETRIEVAL_CACHE_DIR set, one
search() result is stored per query, date and retrieval parameters, and every
configuration with the same chunker and parameters reuses it. Off by default:
a server has no use for it.

The key includes a fingerprint of the corpus files and of the embedding and
reranking models, so changing either starts a fresh cache. A cached search
costs nothing, which makes latency incomparable between configurations - the
eval report records that the cache was on.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from grounded_rag.config import RetrievalConfig, settings
from grounded_rag.types import Chunk

Hits = list[tuple[Chunk, float]]


def enabled() -> bool:
    return bool(settings.retrieval_cache_dir)


@lru_cache(maxsize=1)
def fingerprint() -> str:
    h = hashlib.sha256()
    for path in sorted(Path(settings.retrieval_cache_corpus).glob("*.md")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    h.update("|".join([settings.qdrant_collection, settings.embedding_model,
                       settings.reranker_model, settings.llm_provider]).encode())
    return h.hexdigest()[:16]


def _path(query: str, as_of: date | None, r: RetrievalConfig) -> Path:
    key = json.dumps({
        "query": query, "as_of": as_of.isoformat() if as_of else None, "chunker": r.chunker,
        "dense": r.top_k_dense, "sparse": r.top_k_sparse, "hybrid": r.hybrid,
        "candidates": r.rerank_candidates, "rerank_to": r.rerank_to, "index": fingerprint(),
    }, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(key.encode()).hexdigest()
    return Path(settings.retrieval_cache_dir) / digest[:2] / f"{digest}.json"


def get(query: str, as_of: date | None, r: RetrievalConfig) -> Hits | None:
    path = _path(query, as_of, r)
    if not path.exists():
        return None
    stored = json.loads(path.read_text(encoding="utf-8"))
    return [(Chunk.model_validate(c), s) for c, s in stored]


def put(query: str, as_of: date | None, r: RetrievalConfig, hits: Hits) -> None:
    path = _path(query, as_of, r)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps([(c.model_dump(mode="json"), s) for c, s in hits],
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: two runs writing the same key never leave half a file
