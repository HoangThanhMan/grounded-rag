"""Matching an answer against the labelled gold clauses.

Gold evidence is matched on text, not on chunk ids. A fixed-size chunk that
contains the gold clause counts exactly like the clause chunk that IS the
gold clause - otherwise the comparison with naive RAG is rigged by
construction. "Contains" means containment, not overlap: phrases like "người
sử dụng lao động" are in every other clause.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from grounded_rag.ingest.chunkers import structural_chunk
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.types import Chunk

WHOLE = 10**9  # no size budget: clauses are cut for indexing, never for measuring
# A clause this long can be cut by a window boundary; half of it is a match.
MIN_WORDS_FOR_HALF = 20
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def gold_text(corpus: Path) -> dict[str, str]:
    """ref -> clause body, without the article heading every clause of the
    article shares. "bo_luat_lao_dong_2019:Điều 35:1" -> "1. Người lao động ..." """
    out: dict[str, str] = {}
    for path in iter_corpus(corpus):
        doc = load_file(path)
        for c in structural_chunk(doc.text, doc.doc_id, max_chars=WHOLE):
            out[c.ref] = c.text.split("\n", 1)[-1]
    return out


def covers(chunk_text: str, gold: str) -> bool:
    """The chunk contains the clause - whole, or the first or second half of
    a clause long enough to straddle a window boundary. Compared word by
    word, so line breaks and punctuation do not matter."""
    want = _words(gold)
    if not want:
        return False
    have = f" {' '.join(_words(chunk_text))} "
    if f" {' '.join(want)} " in have:
        return True
    if len(want) < MIN_WORDS_FOR_HALF:
        return False
    half = len(want) // 2
    return f" {' '.join(want[:half])} " in have or f" {' '.join(want[-half:])} " in have


def matches(chunk: Chunk, ref: str, gold: dict[str, str]) -> bool:
    if chunk.ref == ref:
        return True
    text = gold.get(ref)
    return bool(text) and covers(chunk.text, text)


def numbers(text: str) -> set[str]:
    """Every number in the text, spelled the way the law and a model would
    agree on: "08" and "8" are the same number, "1.000" and "1000" too."""
    out = set()
    for raw in _NUMBER.findall(text):
        digits = raw.replace(".", "").replace(",", "")
        out.add(digits.lstrip("0") or "0")
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())
