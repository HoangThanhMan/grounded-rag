"""Cross-encoder reranking. The retrieval floor reads its score, so this is
also the component that decides when we refuse to answer at all."""

from __future__ import annotations

import functools
from typing import Protocol

from grounded_rag.config import settings
from grounded_rag.retrieval.lexical import tokenize
from grounded_rag.types import Chunk


class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: list[tuple[Chunk, float]], top_n: int
    ) -> list[tuple[Chunk, float]]: ...


class LexicalReranker:
    """Mock-mode stand-in: the share of the query's tokens the passage contains.

    Crude, but on the same 0-1 scale as the real reranker, so the retrieval
    floor behaves like a floor in the mock pipeline instead of rejecting
    everything.
    """

    def rerank(self, query, candidates, top_n):
        q = set(tokenize(query))
        if not q:
            return []
        scored = [(c, len(q & set(tokenize(c.text))) / len(q)) for c, _ in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


class BGEReranker:
    """bge-reranker-v2-m3. Scores are sigmoid(logit) in [0, 1], computed here
    rather than left to a library default, because `min_score` in the configs
    is a threshold on exactly this scale."""

    def __init__(
        self, model_name: str | None = None, batch_size: int = 16, max_length: int = 512
    ) -> None:
        self.model_name = model_name or settings.reranker_model
        self.batch_size = batch_size
        self.max_length = max_length
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self._model.eval()
        return self._tokenizer, self._model

    def rerank(self, query, candidates, top_n):
        if not candidates:
            return []
        import torch

        tokenizer, model = self._load()
        chunks = [c for c, _ in candidates]
        scores: list[float] = []
        with torch.inference_mode():
            for i in range(0, len(chunks), self.batch_size):
                batch = chunks[i : i + self.batch_size]
                enc = tokenizer(
                    [query] * len(batch),
                    [c.text for c in batch],
                    padding=True,
                    truncation="only_second",
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                logits = model(**enc).logits.view(-1).float()
                scores.extend(torch.sigmoid(logits).tolist())
        ranked = sorted(zip(chunks, scores, strict=True), key=lambda x: x[1], reverse=True)
        return ranked[:top_n]


@functools.lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return LexicalReranker() if settings.llm_provider == "mock" else BGEReranker()
