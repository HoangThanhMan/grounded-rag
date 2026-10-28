"""One question in, the sources the LLM will read out.

    dense (+ BM25) -> reciprocal rank fusion -> cross-encoder rerank -> floor

The scores that come back are rerank scores - the scale `min_score` is set
on. With reranking off (the evaluation's naive RAG) they are whatever the
first stage gave, and the floor is off too.
"""

from __future__ import annotations

from datetime import date

from grounded_rag.config import RetrievalOptions
from grounded_rag.retrieval.embedder import get_embedder
from grounded_rag.retrieval.hybrid import reciprocal_rank_fusion
from grounded_rag.retrieval.reranker import get_reranker
from grounded_rag.retrieval.store import Hits, get_store
from grounded_rag.types import Chunk


def search(query: str, options: RetrievalOptions, as_of: date | None) -> Hits:
    store = get_store(options.chunker)
    dense = store.dense_search(query, options.top_k_dense, as_of)
    if options.hybrid:
        sparse = store.sparse_search(query, options.top_k_sparse, as_of)
        candidates = reciprocal_rank_fusion([dense, sparse])
    else:
        candidates = dense
    candidates = candidates[: options.rerank_candidates]
    if options.rerank:
        hits = get_reranker().rerank(query, candidates, options.top_n)
    else:
        hits = candidates[: options.top_n]
    if options.min_score is not None:
        hits = [(c, s) for c, s in hits if s >= options.min_score]
    return hits


def warm_up() -> None:
    """Load both models now, at startup, so the first person to ask does not
    wait the extra half minute it takes to read them from disk."""
    get_embedder().encode(["khởi động"])
    get_reranker().rerank("khởi động", [(Chunk(chunk_id="w", doc_id="w", text="w"), 0.0)], 1)
