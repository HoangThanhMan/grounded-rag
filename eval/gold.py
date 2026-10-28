"""Matching an answer against the labelled gold clauses.

Gold evidence is matched on text, by the same rule for both systems - never
on chunk ids, which only the clause chunker produces. A source holds a gold
clause if it contains the whole clause, or an unbroken run of RUN_WORDS words
of it: a long clause is split into pieces by the clause chunker and cut by
window edges in fixed-size chunks, and either way a piece is evidence. Short
shared phrases are not - "người sử dụng lao động" is in every other clause.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from grounded_rag.ingest.chunkers import structural_chunk
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.types import Chunk

WHOLE = 10**9  # no size budget: clauses are cut for indexing, never for measuring
# Legal boilerplate repeats in short phrases, not in 30-word runs.
RUN_WORDS = 30
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
    """Compared word by word, so line breaks and punctuation do not matter."""
    want = _words(gold)
    if not want:
        return False
    have = _words(chunk_text)
    if len(want) <= RUN_WORDS:
        return f" {' '.join(want)} " in f" {' '.join(have)} "
    runs = {tuple(want[i : i + RUN_WORDS]) for i in range(len(want) - RUN_WORDS + 1)}
    return any(tuple(have[i : i + RUN_WORDS]) in runs for i in range(len(have) - RUN_WORDS + 1))


def matches(chunk: Chunk, ref: str, gold: dict[str, str]) -> bool:
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
