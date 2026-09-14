"""Reciprocal Rank Fusion of dense and sparse result lists."""

from __future__ import annotations

from grounded_rag.types import Chunk

K = 60  # RRF damping constant, the usual default


def reciprocal_rank_fusion(
    runs: list[list[tuple[Chunk, float]]], k: int = K
) -> list[tuple[Chunk, float]]:
    scores: dict[str, float] = {}
    seen: dict[str, Chunk] = {}
    for run in runs:
        for rank, (chunk, _) in enumerate(run):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            seen[chunk.chunk_id] = chunk
    fused = [(seen[cid], score) for cid, score in scores.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused
