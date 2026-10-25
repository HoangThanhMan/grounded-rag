"""The lexical half of hybrid search: a Vietnamese-aware tokenizer and BM25.

Why BM25 next to dense vectors: legal questions hinge on exact tokens -
"Điều 35", "45 ngày", "48 giờ" - that embeddings blur together. BM25 needs no
model, so the mock pipeline and CI get real lexical retrieval as well.

The same scoring runs in two places:
  BM25Index       in-process, behind InMemoryStore
  sparse vectors  in Qdrant; the document side carries BM25's saturated term
                  frequency and Qdrant applies IDF at query time (Modifier.IDF)
"""

from __future__ import annotations

import math
import re
import unicodedata
import zlib
from collections import Counter

K1 = 1.2
B = 0.75
_WORD_RE = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    """Lower-cased syllables plus adjacent-syllable bigrams.

    Vietnamese writes multi-syllable words with spaces ("hợp đồng lao động"),
    so bigrams approximate word segmentation without a segmenter dependency.
    Numbers lose leading zeros: the corpus writes "08 giờ", people ask "8 giờ".
    """
    words = _WORD_RE.findall(unicodedata.normalize("NFC", text).lower())
    syllables = [str(int(w)) if w.isdecimal() else w for w in words]
    return syllables + [f"{a}_{b}" for a, b in zip(syllables, syllables[1:], strict=False)]


def idf(n_docs: int, df: int) -> float:
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def tf_weight(tf: int, doc_len: int, avg_len: float) -> float:
    return tf * (K1 + 1) / (tf + K1 * (1 - B + B * doc_len / avg_len))


class BM25Index:
    def __init__(self) -> None:
        self._docs: list[Counter[str]] = []
        self._lens: list[int] = []
        self._df: Counter[str] = Counter()

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, tokens: list[str]) -> None:
        tf = Counter(tokens)
        self._docs.append(tf)
        self._lens.append(len(tokens))
        self._df.update(tf.keys())

    def scores(self, query_tokens: list[str]) -> list[float]:
        n = len(self._docs)
        if not n:
            return []
        avg_len = sum(self._lens) / n or 1.0
        terms = [(t, idf(n, self._df[t])) for t in set(query_tokens) if self._df[t]]
        return [
            sum(w * tf_weight(tf[t], dl, avg_len) for t, w in terms if t in tf)
            for tf, dl in zip(self._docs, self._lens, strict=True)
        ]


def sparse_doc_vector(tokens: list[str], avg_len: float) -> tuple[list[int], list[float]]:
    weights: dict[int, float] = {}
    for token, tf in Counter(tokens).items():
        i = _index(token)
        weights[i] = weights.get(i, 0.0) + tf_weight(tf, len(tokens), avg_len or 1.0)
    return list(weights), list(weights.values())


def sparse_query_vector(tokens: list[str]) -> tuple[list[int], list[float]]:
    indices = sorted({_index(t) for t in tokens})
    return indices, [1.0] * len(indices)


def _index(token: str) -> int:
    """Stable across processes, unlike hash(). A collision in a vocabulary of a
    few tens of thousands merely merges two terms' weights."""
    return zlib.crc32(token.encode())
