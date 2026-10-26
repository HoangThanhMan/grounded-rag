from datetime import date

from grounded_rag.config import RetrievalConfig, RunConfig, settings
from grounded_rag.retrieval import cache, corrective
from grounded_rag.types import Chunk


def _hits():
    return [(Chunk(chunk_id="law:Điều 1:1", doc_id="law", text="Điều 1.\n1. Nội dung."), 0.9)]


def test_a_cached_search_is_returned_without_searching(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "retrieval_cache_dir", str(tmp_path / "c"))
    monkeypatch.setattr(settings, "retrieval_cache_corpus", str(tmp_path))
    cache.fingerprint.cache_clear()
    calls = []

    class Store:
        def dense_search(self, *a):
            calls.append("dense")
            return [(_hits()[0][0], 1.0)]

        def sparse_search(self, *a):
            return []

    class Reranker:
        def rerank(self, query, fused, k):
            return _hits()

    monkeypatch.setattr(corrective, "get_store", lambda chunker: Store())
    monkeypatch.setattr(corrective, "get_reranker", lambda: Reranker())
    config = RunConfig()
    first = corrective.search("câu hỏi", config, date(2026, 1, 1))
    second = corrective.search("câu hỏi", config, date(2026, 1, 1))
    assert first == second and calls == ["dense"]
    # another date is another search: a clause can be in force on one and not the other
    corrective.search("câu hỏi", config, date(2024, 1, 1))
    assert calls == ["dense", "dense"]


def test_the_key_changes_with_retrieval_parameters_and_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "retrieval_cache_dir", str(tmp_path / "c"))
    monkeypatch.setattr(settings, "retrieval_cache_corpus", str(tmp_path))
    (tmp_path / "law.md").write_text("Điều 1. A", encoding="utf-8")
    cache.fingerprint.cache_clear()
    on = date(2026, 1, 1)
    cache.put("q", on, RetrievalConfig(rerank_to=5), _hits())
    assert cache.get("q", on, RetrievalConfig(rerank_to=5)) == _hits()
    assert cache.get("q", on, RetrievalConfig(rerank_to=3)) is None
    (tmp_path / "law.md").write_text("Điều 1. B", encoding="utf-8")
    cache.fingerprint.cache_clear()
    assert cache.get("q", on, RetrievalConfig(rerank_to=5)) is None


def test_an_empty_search_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "retrieval_cache_dir", str(tmp_path / "c"))
    monkeypatch.setattr(settings, "retrieval_cache_corpus", str(tmp_path))
    cache.fingerprint.cache_clear()

    class Store:
        def dense_search(self, *a):
            return []

        def sparse_search(self, *a):
            return []

    class Reranker:
        def rerank(self, query, fused, k):
            return []

    monkeypatch.setattr(corrective, "get_store", lambda chunker: Store())
    monkeypatch.setattr(corrective, "get_reranker", lambda: Reranker())
    corrective.search("câu hỏi", RunConfig(), date(2026, 1, 1))
    assert cache.get("câu hỏi", date(2026, 1, 1), RunConfig().retrieval) is None
