"""Split an answer into claims - one verifiable statement each.

Sentence splitting in Vietnamese legal text is not trivial: "Điều 35." and
"khoản 1." both end in a period without ending a sentence. The abbreviation
list below is the whole trick; keep it in sync with the corpus.
"""

from __future__ import annotations

import re

from grounded_rag.generation.citation import extract_citations, strip_citations
from grounded_rag.types import Claim

# tokens that end with '.' but do not end a sentence
_PROTECTED = [
    "Điều",
    "Khoản",
    "Điểm",
    "Chương",
    "Mục",
    "TT",
    "NĐ",
    "CP",
    "vd",
    "v.v",
]
_PROTECTED_RE = re.compile(
    rf"\b({'|'.join(map(re.escape, _PROTECTED))})\s+(\d+)\.", re.IGNORECASE
)
_DOT = "<DOT>"
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZĐÀÁẢÃẠÂĂÊÔƠƯ])")
# Models put the marker on either side of the full stop. "Câu một. [C1] Câu
# hai." would otherwise hand [C1] to the second sentence, so move it inside.
_CITES_AFTER_STOP = re.compile(r"([.!?])((?:\s*\[C\d+\])+)")
_LIST_MARKER = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+")
_HAS_WORD = re.compile(r"[^\W\d_]")


def split_claims(answer: str) -> list[Claim]:
    # Every line is at least one claim: models answer in lists as often as in
    # prose, and a list item often has no full stop to split on.
    claims: list[Claim] = []
    for line in answer.splitlines():
        claims.extend(_split_sentences(_LIST_MARKER.sub("", line)))
    return claims


def _split_sentences(text: str) -> list[Claim]:
    protected = _CITES_AFTER_STOP.sub(lambda m: f"{m.group(2)}{m.group(1)}", text)
    protected = _PROTECTED_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}{_DOT}", protected)

    claims: list[Claim] = []
    for sentence in _SENT_END.split(protected):
        sentence = sentence.replace(_DOT, ".").strip()
        body = strip_citations(sentence)
        if not _HAS_WORD.search(body):  # "1.", "-", a stray "[C2]": nothing to verify
            continue
        claims.append(Claim(text=body, citations=extract_citations(sentence)))
    return claims
