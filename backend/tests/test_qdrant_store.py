"""QdrantStore against Qdrant's embedded ':memory:' mode - the production code
path (named dense + sparse vectors, IDF modifier, payload filters) without a
server. HashEmbedder stands in for bge-m3."""

from datetime import date
from pathlib import Path

import pytest

from grounded_rag.ingest.chunkers import structural_chunk
from grounded_rag.ingest.loaders import load_file
from grounded_rag.retrieval.embedder import HashEmbedder
from grounded_rag.retrieval.store import QdrantStore

qdrant_client = pytest.importorskip("qdrant_client")


@pytest.fixture
def store():
    client = qdrant_client.QdrantClient(location=":memory:")
    return QdrantStore("test", client=client, embedder=HashEmbedder())


@pytest.fixture
def chunks():
    doc = load_file(Path("data/sample_corpus/bo_luat_lao_dong_2019.md"))
    return structural_chunk(doc.text, doc.doc_id, meta=doc.meta)


def test_upsert_is_idempotent(store, chunks):
    assert store.upsert(chunks) == len(chunks)
    assert store.upsert(chunks) == 0


def test_sparse_search_finds_the_clause_by_its_terms(store, chunks):
    store.upsert(chunks)
    top, _ = store.sparse_search("nghỉ hằng năm hưởng nguyên lương", 3)[0]
    assert top.ref == "bo_luat_lao_dong_2019:Điều 113:1"


def test_payload_round_trips_to_the_same_chunk(store, chunks):
    store.upsert(chunks)
    hit, score = store.dense_search(chunks[0].text, 1)[0]  # same text -> same hash vector
    assert hit == chunks[0]
    assert score == pytest.approx(1.0)


def test_validity_filter_runs_inside_qdrant(store, chunks):
    store.upsert(chunks)  # the sample corpus takes effect on 2021-01-01
    assert store.sparse_search("nghỉ hằng năm", 5, as_of=date(2020, 1, 1)) == []
    assert store.sparse_search("nghỉ hằng năm", 5, as_of=date(2025, 1, 1))


def test_reset_drops_the_index(store, chunks):
    store.upsert(chunks)
    store.reset()
    assert store.upsert(chunks) == len(chunks)


def test_delete_document_removes_only_that_doc(store, chunks):
    other = [c.model_copy(update={"doc_id": "khac", "chunk_id": f"khac:{c.chunk_id}"})
             for c in chunks]
    store.upsert(chunks + other)
    store.delete_document("bo_luat_lao_dong_2019")
    left = {c.doc_id for c, _ in store.sparse_search("nghỉ hằng năm", 20)}
    assert left == {"khac"}


def test_in_memory_store_deletes_a_document_too(chunks):
    from grounded_rag.retrieval.store import InMemoryStore

    mem = InMemoryStore(HashEmbedder())
    other = [c.model_copy(update={"doc_id": "khac", "chunk_id": f"khac:{c.chunk_id}"})
             for c in chunks]
    mem.upsert(chunks + other)
    mem.delete_document("bo_luat_lao_dong_2019")
    assert {c.doc_id for c, _ in mem.sparse_search("nghỉ hằng năm", 20)} == {"khac"}
    mem.upsert(chunks)  # a re-indexed document comes back
    assert {c.doc_id for c, _ in mem.sparse_search("nghỉ hằng năm", 20)} == {
        "khac", "bo_luat_lao_dong_2019"}
