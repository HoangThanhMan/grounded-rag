"""Metrics for the benchmark.

Definitions matter more than the code here: every configuration is scored by
this one module, after the fact. Two rules the numbers depend on:

  - One measuring instrument for every configuration. Hallucination is judged
    on the final answer text, by the same verifier at the same threshold,
    whether or not the configuration ran a guard (`Row.judged`, produced in
    eval/run.py). A baseline judged by a different yardstick is not a baseline.
  - Gold evidence is matched on text, not on chunk ids. A recursive chunk that
    contains the gold clause counts exactly like the structural chunk that IS
    the gold clause - otherwise the chunker comparison is rigged by construction.
    "Contains" means containment, not overlap: phrases like "người sử dụng lao
    động" are in every other clause, and an overlap measure found 15-39 clauses
    "inside" a single 1,200-character window.

Every rate is a mean of per-question values (`case_scores`), and the report
stores those values next to each case. That is what lets eval/report.py put a
bootstrap interval on any column without the corpus or a model.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from grounded_rag.generation.citation import extract_citations, strip_citations
from grounded_rag.guard.nli_verifier import numbers
from grounded_rag.types import Answer, AnswerStatus, Chunk, Claim, RetrievedChunk, Verdict

ABSTAIN_STATES = {AnswerStatus.ABSTAINED, AnswerStatus.NO_CONTEXT}
# A clause this long can be cut by a window boundary; half of it is a match.
MIN_WORDS_FOR_HALF = 20
RECALL_AT = (1, 3, 5)


@dataclass
class Case:
    id: str
    answerable: bool
    gold_chunks: list[str] = field(default_factory=list)
    type: str = "answerable"
    tags: list[str] = field(default_factory=list)
    gold_answer: str | None = None


@dataclass
class Row:
    case: Case
    answer: Answer
    judged: list[Claim] = field(default_factory=list)  # verdicts from the eval instrument


def abstained(answer: Answer) -> bool:
    return answer.status in ABSTAIN_STATES


def hallucinated(row: Row) -> bool:
    """An answer hallucinates if it asserts anything its cited source does not
    support - an uncited claim counts, silence does not."""
    if abstained(row.answer):
        return False
    return any(c.verdict is not Verdict.SUPPORTED for c in row.judged)


def covers(chunk_text: str, gold_text: str, *, whole_only: bool = False) -> bool:
    """The chunk contains the clause - whole, or (unless whole_only) the first
    or second half of a clause long enough to straddle a window boundary.
    Compared word by word, so line breaks and punctuation do not matter."""
    gold = _words(gold_text)
    if not gold:
        return False
    chunk = f" {' '.join(_words(chunk_text))} "
    if f" {' '.join(gold)} " in chunk:
        return True
    if whole_only or len(gold) < MIN_WORDS_FOR_HALF:
        return False
    half = len(gold) // 2
    return f" {' '.join(gold[:half])} " in chunk or f" {' '.join(gold[-half:])} " in chunk


def matches(chunk: Chunk, gold_ref: str, gold_text: dict[str, str]) -> bool:
    if chunk.ref == gold_ref:
        return True
    text = gold_text.get(gold_ref)
    return bool(text) and covers(chunk.text, text)


def cited_sources(answer: Answer) -> list[RetrievedChunk]:
    """Sources cited in the final answer text - not in claims the guard dropped."""
    labels = set(extract_citations(answer.answer))
    return [s for s in answer.sources if s.label in labels]


def citation_precision_recall(
    answer: Answer, gold: list[str], gold_text: dict[str, str]
) -> tuple[float, float]:
    if not gold:
        return (1.0, 1.0)
    cited = cited_sources(answer)
    if not cited:
        return (0.0, 0.0)
    good = [s for s in cited if any(matches(s.chunk, g, gold_text) for g in gold)]
    found = [g for g in gold if any(matches(s.chunk, g, gold_text) for s in cited)]
    return (len(good) / len(cited), len(found) / len(gold))


def retrieval_recall(answer: Answer, gold: list[str], gold_text: dict[str, str]) -> float:
    """Share of the gold evidence that reached the model's context at all."""
    if not gold:
        return 1.0
    hits = sum(any(matches(s.chunk, g, gold_text) for s in answer.sources) for g in gold)
    return hits / len(gold)


def recall_at(answer: Answer, gold: list[str], gold_text: dict[str, str], k: int) -> float:
    """Share of the gold evidence among the top k sources, in rerank order."""
    if not gold:
        return 1.0
    top = answer.sources[:k]
    return sum(any(matches(s.chunk, g, gold_text) for s in top) for g in gold) / len(gold)


def reciprocal_rank(answer: Answer, gold: list[str], gold_text: dict[str, str]) -> float:
    """1 / rank of the first source holding any gold evidence; 0 if none does."""
    for rank, s in enumerate(answer.sources, start=1):
        if any(matches(s.chunk, g, gold_text) for g in gold):
            return 1.0 / rank
    return 0.0


def answer_correct(answer: Answer, gold_answer: str | None) -> bool | None:
    """Every number in the gold answer is in the answer. None when the gold
    answer has no number to check.

    Grounded is not correct: the guard asks whether a claim follows from the
    passage it cites, not whether it answers the question. In this corpus the
    answer usually *is* a number - "45 ngày", "30%" - so the numbers are a
    cheap, model-free proxy for correctness. Citation labels are stripped
    first, or the "1" in [C1] would count. A refusal is not a correct answer.

    It also measures completeness against the gold answer: when the gold
    answer adds a second number the question did not ask for ("10 giờ/ngày"
    asked, "48 giờ/tuần" added), an answer to exactly the question fails.
    """
    want = numbers(gold_answer or "")
    if not want:
        return None
    if abstained(answer):
        return False
    return want <= numbers(strip_citations(answer.answer))


def case_scores(row: Row, gold_text: dict[str, str]) -> dict[str, float | None]:
    """The per-question values every rate is a mean of. None: the question is
    not in that rate's denominator."""
    answer, case = row.answer, row.case
    out: dict[str, float | None] = {
        "hallucination_rate": float(hallucinated(row)),
        **dict.fromkeys(
            ["correct_abstention", "false_abstention", "citation_precision", "citation_recall",
             "retrieval_recall", *(f"recall_at_{k}" for k in RECALL_AT), "mrr",
             "answer_correctness"]
        ),
    }
    if not case.answerable:
        out["correct_abstention"] = float(abstained(answer))
        return out
    gold = case.gold_chunks
    out["false_abstention"] = float(abstained(answer))
    # Citation quality is measured where there is an answer to cite from;
    # refusing an answerable question is false_abstention's job to count.
    if not abstained(answer):
        out["citation_precision"], out["citation_recall"] = citation_precision_recall(
            answer, gold, gold_text
        )
    out["retrieval_recall"] = retrieval_recall(answer, gold, gold_text)
    for k in RECALL_AT:
        out[f"recall_at_{k}"] = recall_at(answer, gold, gold_text, k)
    out["mrr"] = reciprocal_rank(answer, gold, gold_text) if gold else None
    correct = answer_correct(answer, case.gold_answer)
    out["answer_correctness"] = None if correct is None else float(correct)
    return out


def rates(scores: list[dict[str, float | None]]) -> dict[str, float]:
    """Mean of each per-question value over the questions it applies to."""
    keys = dict.fromkeys(k for s in scores for k in s)
    return {k: _mean(s[k] for s in scores if s.get(k) is not None) for k in keys}


def aggregate(rows: list[Row], gold_text: dict[str, str] | None = None) -> dict:
    if not rows:
        return {}
    gold_text = gold_text or {}
    ans = [r for r in rows if r.case.answerable]
    unans = [r for r in rows if not r.case.answerable]
    scores = [case_scores(r, gold_text) for r in rows]
    lat = sorted(r.answer.meta.latency_ms for r in rows)

    return {
        "n": len(rows),
        **rates(scores),
        "answer_correctness_n": sum(s["answer_correctness"] is not None for s in scores),
        "latency_p50_ms": _pct(lat, 0.50),
        "latency_p95_ms": _pct(lat, 0.95),
        "tokens_total": sum(r.answer.meta.tokens for r in rows),
        "llm_calls_per_q": _mean(r.answer.meta.llm_calls for r in rows),
        "cost_usd_total": round(sum(r.answer.meta.cost_usd for r in rows), 6),
        # Answers cut off at max_tokens. Anything above 0 means the numbers
        # measure the token budget, not the guard - fix the config first.
        "truncated_generations": sum(
            bool(s.detail.get("truncated")) for r in rows for s in r.answer.meta.steps
        ),
        "correct_abstention_by_layer": _by_layer(unans),
        "by_type": _by_type(rows),
        "by_tag": _by_tag(ans, gold_text),
    }


def _by_layer(unans: list[Row]) -> dict[str, float]:
    """Which defence caught the unanswerable questions. Sums to correct_abstention."""
    if not unans:
        return {}
    caught = Counter(
        str(r.answer.meta.abstain_reason or "unknown") for r in unans if abstained(r.answer)
    )
    return {reason: round(n / len(unans), 4) for reason, n in sorted(caught.items())}


def _by_type(rows: list[Row]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for t in sorted({r.case.type for r in rows}):
        group = [r for r in rows if r.case.type == t]
        out[t] = {
            "n": len(group),
            "abstention_rate": _mean(abstained(r.answer) for r in group),
            "hallucination_rate": _mean(hallucinated(r) for r in group),
        }
    return out


def _by_tag(ans: list[Row], gold_text: dict[str, str]) -> dict[str, dict[str, float]]:
    """Answerable slices - e.g. multi_part, colloquial - where one averaged
    number would hide what the corrective loop is for."""
    out: dict[str, dict[str, float]] = {}
    for tag in sorted({t for r in ans for t in r.case.tags}):
        group = [r for r in ans if tag in r.case.tags]
        out[tag] = {
            "n": len(group),
            "false_abstention": _mean(abstained(r.answer) for r in group),
            "retrieval_recall": _mean(
                retrieval_recall(r.answer, r.case.gold_chunks, gold_text) for r in group
            ),
        }
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def _mean(values) -> float:
    vals = [float(v) for v in values]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _pct(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    idx = min(int(q * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[idx]
