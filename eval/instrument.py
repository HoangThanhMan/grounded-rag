"""The measuring instrument: how the eval decides whether a claim is supported.

Every configuration is judged by the same NLI model at the same threshold -
and, just as important, against premises of the same size. A claim is scored
against the chunk it cites, against every whole clause of the corpus that
chunk contains, and against all its cited chunks joined; the best score counts.

Why the clause-sized premises: the NLI model reads 512 tokens, and recursive
windows run 565-680. On the first real run, correct claims scored 0.02-0.32
against the recursive window they cited and 0.85-0.97 against the clause
inside it (docs/07-evaluation-plan.md). Judged on raw windows, the baseline
"hallucinated" in 57% of answers that were in fact right - a number about
chunk size, not about the guard.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from eval.metrics import ABSTAIN_STATES, covers
from grounded_rag.guard.claim_splitter import split_claims
from grounded_rag.guard.nli_verifier import Verifier
from grounded_rag.ingest.chunkers import structural_chunk
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.types import Answer, Chunk, Claim, Verdict

WHOLE = 10**9  # no size budget: clauses are cut for indexing, never for measuring


class ClauseIndex:
    """Every clause of the corpus, whole, with its article heading."""

    def __init__(self, corpus: Path | None) -> None:
        self.clauses: list[Chunk] = []
        if corpus and corpus.exists():
            for path in iter_corpus(corpus):
                doc = load_file(path)
                self.clauses += structural_chunk(doc.text, doc.doc_id, max_chars=WHOLE)

    def gold_text(self) -> dict[str, str]:
        """ref -> clause body without the heading, which every clause of an
        article shares. What gold refs are matched against."""
        return {c.ref: c.text.split("\n", 1)[-1] for c in self.clauses}

    def premises(self, chunk: Chunk) -> list[str]:
        """The chunk as cited, plus - for a window with no legal structure of
        its own - each clause it contains whole, and each pair of neighbouring
        ones: one sentence often states two adjacent clauses at once ("08 giờ
        một ngày, hoặc 10 giờ nếu theo tuần"), and the window showed both.

        A structural chunk is judged as cited. Citing one clause for a
        sentence that needs two is under-citing, and "unsupported" is right."""
        if chunk.article:
            return [chunk.text]
        inside = [c.text for c in self.clauses if covers(chunk.text, c.text.split("\n", 1)[-1],
                                                         whole_only=True)]
        pairs = [_join_clauses(a, b) for a, b in zip(inside, inside[1:], strict=False)]
        return [chunk.text, *inside, *pairs]


def _join_clauses(first: str, second: str) -> str:
    """Two clause texts, the second's heading dropped when both share it."""
    head, _, body = second.partition("\n")
    return f"{first}\n{body}" if first.partition("\n")[0] == head else f"{first}\n{second}"


def judge_claims(
    answer: Answer, verifier: Verifier, threshold: float, index: ClauseIndex
) -> list[Claim]:
    if answer.status in ABSTAIN_STATES:
        return []
    chunks = {s.label: s.chunk for s in answer.sources}
    claims = split_claims(answer.answer)
    for claim in claims:
        cited = [chunks[label] for label in claim.citations if label in chunks]
        if not cited:
            claim.verdict, claim.entailment = Verdict.UNCITED, 0.0
            continue
        premises = [p for chunk in cited for p in index.premises(chunk)]
        if len(cited) > 1:  # a claim may need its sources together, as the guard reads them
            premises.append("\n".join(c.text for c in cited))
        if len(cited) > 2:  # and three joined can pass 512 tokens, as in the guard
            premises += ["\n".join((a.text, b.text)) for a, b in itertools.combinations(cited, 2)]
        score = max(verifier.entailment(p, claim.text) for p in premises)
        claim.entailment = round(score, 4)
        claim.verdict = Verdict.SUPPORTED if score >= threshold else Verdict.UNSUPPORTED
    return claims
