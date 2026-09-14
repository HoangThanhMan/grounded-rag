"""Dense embeddings. bge-m3: multilingual, strong on Vietnamese.

The lexical side of hybrid search is BM25 (retrieval/lexical.py), not
bge-m3's learned sparse output - see docs/adr/0006-bm25-sparse-retrieval.md.
"""

from __future__ import annotations

import functools
import hashlib
from typing import Protocol

from grounded_rag.config import settings

DIM = 1024


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic fake embeddings for tests and the mock pipeline."""

    dim = DIM

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([(h[i % len(h)] - 128) / 128 for i in range(DIM)])
        return out


class BGEEmbedder:
    """sentence-transformers under the hood. Loaded lazily, so importing this
    module never pulls a 2GB checkpoint. Vectors are L2-normalised, which makes
    Qdrant's cosine distance a plain dot product."""

    def __init__(self, model_name: str | None = None, batch_size: int = 16) -> None:
        self.model_name = model_name or settings.embedding_model
        self.batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # `models` extra

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        model = self._load()
        # renamed in sentence-transformers 6; the old name still works, with a warning
        get_dim = getattr(model, "get_embedding_dimension", None)
        return int((get_dim or model.get_sentence_embedding_dimension)())

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


@functools.lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return HashEmbedder() if settings.llm_provider == "mock" else BGEEmbedder()
