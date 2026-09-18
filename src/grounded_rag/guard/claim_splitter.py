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
# Square brackets that are not a [C1] label. Legal text never uses them, but
# small models do, in three ways:
#   "[Điều 105, Khoản 1]" - the article number, next to or instead of the label
#   "[CR1]", "[TRẢ LỜI]"  - an invented tag, all capitals
#   "[60 ngày]"           - the answer itself, bracketed
# The first two are dropped. The third is unwrapped: deleting it turned
# "tối đa là [60 ngày] [C1]" into "tối đa là." and the guard, rightly, refused it.
_BRACKET = re.compile(r"\[(?!C\d+\])([^\]\n]*)\]")
_ARTICLE = re.compile(r"^\s*(?:Điều|Khoản|Điểm|Chương)\b")


def _drop_or_unwrap(inside: str) -> str:
    tag = any(ch.isalpha() for ch in inside) and inside == inside.upper()
    return "" if tag or _ARTICLE.match(inside) else inside


def _unbracket(text: str) -> str:
    out = _BRACKET.sub(lambda m: _drop_or_unwrap(m.group(1)), text)
    return re.sub(r"\s{2,}", " ", out).strip()


# "Câu trả lời: ..." - the model echoing the prompt's answer slot
_ANSWER_PREFIX = re.compile(r"^\s*(?:câu\s+)?trả\s+lời\s*:\s*", re.IGNORECASE)


def split_claims(answer: str) -> list[Claim]:
    # Every line is at least one claim: models answer in lists as often as in
    # prose, and a list item often has no full stop to split on.
    claims: list[Claim] = []
    for line in answer.splitlines():
        line = _ANSWER_PREFIX.sub("", _unbracket(_LIST_MARKER.sub("", line)))
        claims.extend(_split_sentences(line))
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
        if body.endswith(":") and not extract_citations(sentence):
            # "Theo tài liệu:" introduces the list that follows; it states
            # nothing. Counted as an uncited claim it sent every listed answer
            # back for regeneration.
            continue
        claims.append(Claim(text=body, citations=extract_citations(sentence)))
    return claims
