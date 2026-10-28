"""Vector store. Qdrant in production, in-memory when mocking.

One index per chunker. The app reads the structural one; the evaluation's
naive RAG reads a recursive one built from the same corpus. Sharing one index
would let each retrieve the other's chunks.

Point ids derive from content hashes, so re-running ingest overwrites instead
of duplicating - the property that makes `make ingest` safe to repeat.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol

from grounded_rag.config import settings
from grounded_rag.retrieval.embedder import Embedder, get_embedder
from grounded_rag.retrieval.lexical import (
    BM25Index,
    sparse_doc_vector,
    sparse_query_vector,
    tokenize,
)
from grounded_rag.types import Chunk

DENSE = "dense"
SPARSE = "sparse"

Hits = list[tuple[Chunk, float]]


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk]) -> int: ...
    def dense_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits: ...
    def sparse_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits: ...
    def reset(self) -> None: ...
    def delete_document(self, doc_id: str) -> None: ...
    def ping(self) -> None: ...


class InMemoryStore:
    """Cosine and BM25 over python lists. Fine for 100 eval questions, not for 100k docs."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder
        self.reset()

    @property
    def embedder(self) -> Embedder:
        return self._embedder or get_embedder()

    def reset(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []
        self._bm25 = BM25Index()

    def delete_document(self, doc_id: str) -> None:
        keep = [i for i, c in enumerate(self._chunks) if c.doc_id != doc_id]
        chunks, vectors = [self._chunks[i] for i in keep], [self._vectors[i] for i in keep]
        self.reset()
        self._chunks, self._vectors = chunks, vectors
        for c in chunks:
            self._bm25.add(tokenize(c.text))

    def ping(self) -> None:
        pass

    def upsert(self, chunks: list[Chunk]) -> int:
        known = {c.chunk_id for c in self._chunks}
        fresh = list({c.chunk_id: c for c in chunks if c.chunk_id not in known}.values())
        if fresh:
            self._chunks.extend(fresh)
            self._vectors.extend(self.embedder.encode([c.text for c in fresh]))
            for c in fresh:
                self._bm25.add(tokenize(c.text))
        return len(fresh)

    def dense_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits:
        if not self._chunks:
            return []
        q = self.embedder.encode([query])[0]
        scored = [
            (c, _cosine(q, v))
            for c, v in zip(self._chunks, self._vectors, strict=True)
            if _visible(c, as_of)
        ]
        return _top(scored, top_k)

    def sparse_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits:
        scores = self._bm25.scores(tokenize(query))
        scored = [
            (c, s)
            for c, s in zip(self._chunks, scores, strict=True)
            if s > 0 and _visible(c, as_of)
        ]
        return _top(scored, top_k)


class QdrantStore:
    """Two named vectors per point: "dense" (cosine) and "sparse" (BM25, with
    Qdrant applying IDF at query time). The payload is the chunk itself, text
    included, so building a prompt never goes back to the source files."""

    def __init__(
        self, collection: str, client: Any = None, embedder: Embedder | None = None
    ) -> None:
        self.collection = collection
        self._client = client
        self._embedder = embedder
        self._ready = False

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            url = settings.qdrant_url
            self._client = (
                QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url)
            )
        return self._client

    @property
    def embedder(self) -> Embedder:
        return self._embedder or get_embedder()

    def _ensure_collection(self) -> None:
        if self._ready:
            return
        from qdrant_client import models

        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config={
                    DENSE: models.VectorParams(
                        size=self.embedder.dim, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        self._ready = True

    def reset(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self._ready = False

    def delete_document(self, doc_id: str) -> None:
        """Every chunk of a document, before it is indexed again: content-hashed
        ids would keep the chunks of an older version next to the new ones."""
        from qdrant_client import models

        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            self.collection,
            points_selector=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            ),
        )

    def ping(self) -> None:
        self.client.get_collections()

    def upsert(self, chunks: list[Chunk]) -> int:
        from qdrant_client import models

        self._ensure_collection()
        unique = {c.chunk_id: c for c in chunks}
        if not unique:
            return 0
        ids = {cid: _point_id(cid) for cid in unique}

        existing: set[str] = set()
        for batch in _batched(list(ids.values()), 256):
            found = self.client.retrieve(
                self.collection, ids=batch, with_payload=False, with_vectors=False
            )
            existing.update(str(p.id) for p in found)
        # Only new chunks pay for embedding - re-ingesting an unchanged corpus is cheap.
        fresh = [c for cid, c in unique.items() if ids[cid] not in existing]

        # BM25 length normalisation is relative to the whole batch, not the new part.
        avg_len = sum(len(tokenize(c.text)) for c in unique.values()) / len(unique)
        now = datetime.now(UTC).isoformat()
        for batch in _batched(fresh, 64):
            dense = self.embedder.encode([c.text for c in batch])
            points = []
            for chunk, vector in zip(batch, dense, strict=True):
                indices, values = sparse_doc_vector(tokenize(chunk.text), avg_len)
                points.append(
                    models.PointStruct(
                        id=ids[chunk.chunk_id],
                        vector={
                            DENSE: vector,
                            SPARSE: models.SparseVector(indices=indices, values=values),
                        },
                        payload={**chunk.model_dump(mode="json"), "ingested_at": now},
                    )
                )
            self.client.upsert(self.collection, points=points)
        return len(fresh)

    def dense_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits:
        self._ensure_collection()
        return self._query(self.embedder.encode([query])[0], DENSE, top_k, as_of)

    def sparse_search(self, query: str, top_k: int, as_of: date | None = None) -> Hits:
        from qdrant_client import models

        indices, values = sparse_query_vector(tokenize(query))
        if not indices:
            return []
        self._ensure_collection()
        vector = models.SparseVector(indices=indices, values=values)
        return self._query(vector, SPARSE, top_k, as_of)

    def _query(self, vector: Any, using: str, top_k: int, as_of: date | None) -> Hits:
        res = self.client.query_points(
            self.collection,
            query=vector,
            using=using,
            limit=top_k,
            query_filter=_in_force_filter(as_of),
            with_payload=True,
        )
        return [(Chunk.model_validate(p.payload), p.score) for p in res.points]


def _in_force_filter(as_of: date | None):
    """Qdrant's version of Chunk.in_force. A missing date never excludes a chunk."""
    if as_of is None:
        return None
    from qdrant_client import models

    day = as_of.isoformat()

    def missing_or(key: str, bound: models.DatetimeRange) -> models.Filter:
        return models.Filter(
            should=[
                models.IsEmptyCondition(is_empty=models.PayloadField(key=key)),
                models.FieldCondition(key=key, range=bound),
            ]
        )

    return models.Filter(
        must=[
            missing_or("effective_date", models.DatetimeRange(lte=day)),
            missing_or("expiry_date", models.DatetimeRange(gt=day)),
        ]
    )


def _visible(chunk: Chunk, as_of: date | None) -> bool:
    return as_of is None or chunk.in_force(as_of)


def _top(scored: Hits, k: int) -> Hits:
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _batched[T](items: Sequence[T], n: int) -> Iterator[list[T]]:
    for i in range(0, len(items), n):
        yield list(items[i : i + n])


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@functools.cache
def get_store(chunker: str = "structural") -> VectorStore:
    if settings.llm_provider == "mock":
        return InMemoryStore()
    return QdrantStore(f"{settings.qdrant_collection}_{chunker}")
