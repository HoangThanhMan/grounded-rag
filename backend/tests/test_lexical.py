from datetime import date

from grounded_rag.retrieval.embedder import HashEmbedder
from grounded_rag.retrieval.lexical import BM25Index, tokenize
from grounded_rag.retrieval.store import InMemoryStore
from grounded_rag.types import Chunk


def _chunk(i: int, text: str, **kw) -> Chunk:
    return Chunk(chunk_id=f"d:{i}", doc_id="d", text=text, **kw)


def _ids(hits) -> set[str]:
    return {c.chunk_id for c, _ in hits}


def test_tokens_include_syllable_bigrams():
    assert "hợp_đồng" in tokenize("Hợp đồng lao động")


def test_numbers_lose_leading_zeros():
    # the corpus writes "08 giờ", people ask "8 giờ"
    assert "8_giờ" in tokenize("không quá 08 giờ")


def test_bm25_ranks_the_matching_clause_first():
    index = BM25Index()
    docs = [
        "thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày",
        "người lao động được nghỉ hằng năm 12 ngày làm việc",
        "phải báo trước ít nhất 45 ngày",
    ]
    for d in docs:
        index.add(tokenize(d))
    scores = index.scores(tokenize("được nghỉ hằng năm bao nhiêu ngày"))
    assert max(range(len(docs)), key=scores.__getitem__) == 1


def test_sparse_search_returns_only_chunks_sharing_a_term():
    store = InMemoryStore(embedder=HashEmbedder())
    store.upsert([
        _chunk(1, "phải báo trước ít nhất 45 ngày"),
        _chunk(2, "tiền lương tối thiểu vùng"),
    ])
    assert _ids(store.sparse_search("báo trước bao lâu", 5)) == {"d:1"}


def test_regulations_not_in_force_are_never_retrieved():
    store = InMemoryStore(embedder=HashEmbedder())
    store.upsert([
        _chunk(1, "nghỉ hằng năm 12 ngày", expiry_date=date(2021, 1, 1)),
        _chunk(2, "nghỉ hằng năm 12 ngày làm việc", effective_date=date(2021, 1, 1)),
    ])
    assert _ids(store.sparse_search("nghỉ hằng năm", 5, as_of=date(2025, 1, 1))) == {"d:2"}
    assert _ids(store.sparse_search("nghỉ hằng năm", 5, as_of=date(2020, 6, 1))) == {"d:1"}
    assert _ids(store.dense_search("nghỉ hằng năm", 5, as_of=date(2025, 1, 1))) == {"d:2"}
