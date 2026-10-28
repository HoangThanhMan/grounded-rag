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
from grounded_rag.types import DocMeta

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
    hit, score = store.dense_search(chunks[0].search_text, 1)[0]  # same text -> same hash vector
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


def test_the_default_store_is_the_structural_index():
    from grounded_rag.retrieval.store import get_store

    assert get_store() is get_store("structural")


def test_upsert_in_batches_scores_like_one_upsert_given_the_corpus_length(chunks):
    from grounded_rag.retrieval.lexical import tokenize

    whole = QdrantStore("a", client=qdrant_client.QdrantClient(location=":memory:"),
                        embedder=HashEmbedder())
    batched = QdrantStore("b", client=qdrant_client.QdrantClient(location=":memory:"),
                          embedder=HashEmbedder())
    whole.upsert(chunks)
    avg = sum(len(tokenize(c.search_text)) for c in chunks) / len(chunks)
    batched.upsert(chunks[:1], avg_len=avg)
    batched.upsert(chunks[1:], avg_len=avg)
    q = "nghỉ hằng năm hưởng nguyên lương"
    assert [round(s, 6) for _, s in whole.sparse_search(q, 5)] == [
        round(s, 6) for _, s in batched.sparse_search(q, 5)]


def test_an_index_built_by_another_embedding_model_is_a_clear_error(chunks):
    class Small(HashEmbedder):
        dim = 384

    client = qdrant_client.QdrantClient(location=":memory:")
    QdrantStore("dims", client=client, embedder=HashEmbedder()).upsert(chunks[:1])
    with pytest.raises(RuntimeError, match="1024.*384|384.*1024"):
        QdrantStore("dims", client=client, embedder=Small()).dense_search("x", 1)


def test_a_clause_is_found_by_words_only_its_chapter_holds(store):
    meta = DocMeta(title="Luật Bảo hiểm xã hội 2024")
    text = ("Chương VI\nBẢO HIỂM XÃ HỘI TỰ NGUYỆN\n"
            "Điều 95. Trợ cấp thai sản\n1. Mức 2.000.000 đồng.\n")
    store.upsert(structural_chunk(text, "bhxh", meta=meta))
    assert store.sparse_search("tự nguyện", 1)


def test_a_document_indexed_by_an_older_version_counts_as_missing(store, chunks):
    """Its chunks lack what retrieval now reads, so startup has to redo them."""
    from grounded_rag.retrieval import store as store_module

    store.upsert(chunks[:1])
    assert store.has_document("bo_luat_lao_dong_2019")
    old = store.client.scroll("test", limit=1)[0][0]
    store.client.overwrite_payload(
        "test", payload={k: v for k, v in old.payload.items() if k != "index_version"},
        points=[old.id],
    )
    assert not store.has_document("bo_luat_lao_dong_2019")
    assert store_module.INDEX_VERSION >= 2
