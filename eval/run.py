"""The one evaluation: does the app cite the right clause, and refuse when
the law says nothing - compared with a naive RAG on the same questions?

    python -m eval.run --system naive
    python -m eval.run --system app
    python -m eval.report

`--set hard` asks the hard questions instead: answers that need several
clauses, maybe of two laws; questions where a clause of the voluntary scheme
reads like the answer for an employee; and comparisons of the 2014 and 2024
laws. They are kept out of the 100-question sample, so adding one never
changes which questions the main table is computed on.

Both systems run through the same pipeline, prompt and LLM. What differs is
only what this project adds for legal text: clause-level chunks, hybrid
search, a reranker and a retrieval floor. Results are appended question by
question to eval/results/<system>.jsonl, so a run stopped by a spent
free-tier quota picks up where it stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import date
from pathlib import Path
from typing import Any

from eval.gold import gold_text, matches, numbers
from grounded_rag.config import RetrievalOptions
from grounded_rag.generation.citation import strip_citations
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.service import answer_question
from grounded_rag.types import Answer, AnswerStatus

DATASET = Path("eval/questions.jsonl")
RESULTS = Path("eval/results")
CORPUS = Path("data/corpus")
# Fixed, so a rerun reads the law exactly as the committed results did.
# Temporal questions carry their own date.
AS_OF = date(2026, 10, 28)

SYSTEMS = {
    "naive": RetrievalOptions(chunker="recursive", hybrid=False, rerank=False, min_score=None),
    "app": RetrievalOptions(),
}
ANSWERABLE = 60
UNANSWERABLE = {
    "unanswerable_out_of_scope": 13,
    "unanswerable_false_premise": 13,
    "unanswerable_near_miss": 14,
}


def select_cases(
    rows: list[dict[str, Any]], question_set: str = "main", seed: int = 7
) -> list[dict[str, Any]]:
    """main: 100 test questions, 60 with an answer in the corpus, 40 without,
    the 40 spread over the three ways a question can have no answer.
    hard: every question of the hard split."""
    if question_set == "hard":
        return sorted((r for r in rows if r["split"] == "hard"), key=lambda r: r["id"])
    rng = random.Random(seed)
    test = sorted((r for r in rows if r["split"] == "test"), key=lambda r: r["id"])
    picked = rng.sample([r for r in test if r["answerable"]], ANSWERABLE)
    for kind, n in UNANSWERABLE.items():
        picked += rng.sample([r for r in test if r["type"] == kind], n)
    return sorted(picked, key=lambda r: r["id"])


def score(case: dict[str, Any], answer: Answer, gold: dict[str, str]) -> dict[str, bool | None]:
    """None: the question is not in that column's denominator.

    `correct` is a proxy, and a strict one: the answer cites a source holding
    the gold clause AND states every number of the gold answer - in this
    corpus the answer usually is a number ("45 ngày", "30%").

    `complete` is stricter still, for answers that need several clauses: it
    cites every gold clause. `cites_wrong_scheme` counts answers citing one of
    the case's `trap_chunks` - the voluntary scheme's clause, asked about an
    employee."""
    refused = answer.status is not AnswerStatus.ANSWERED
    if not case["answerable"]:
        return {
            "hit_at_5": None, "correct": None, "false_refusal": None, "correct_refusal": refused,
            "all_gold_retrieved": None, "complete": None, "cites_wrong_scheme": None,
        }
    refs = case["gold_chunks"]
    top = answer.sources[:5]
    cited = [s for s in answer.sources if s.label in answer.citations]

    def held(sources, ref):
        return any(matches(s.chunk, ref, gold) for s in sources)

    says_numbers = numbers(case["gold_answer"] or "") <= numbers(strip_citations(answer.answer))
    traps = case.get("trap_chunks") or []
    return {
        "hit_at_5": any(held(top, ref) for ref in refs),
        "correct": not refused and any(held(cited, ref) for ref in refs) and says_numbers,
        "false_refusal": refused,
        "correct_refusal": None,
        "all_gold_retrieved": all(held(top, ref) for ref in refs),
        "complete": not refused and all(held(cited, ref) for ref in refs) and says_numbers,
        "cites_wrong_scheme": any(held(cited, ref) for ref in traps) if traps else None,
    }


async def run(
    system: str, cases: list[dict[str, Any]], out: Path, as_of: date, gold: dict[str, str]
) -> int:
    """Answers every case not already in `out`; returns how many it added."""
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text().splitlines() if line}
    out.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    for case in cases:
        if case["id"] in done:
            continue
        on = date.fromisoformat(case["as_of"]) if case.get("as_of") else as_of
        answer = await answer_question(case["question"], as_of=on, options=SYSTEMS[system])
        record = {
            "id": case["id"],
            "type": case["type"],
            "question": case["question"],
            "as_of": on.isoformat(),
            "status": answer.status,
            "abstain_reason": answer.meta.abstain_reason,
            "answer": answer.answer,
            "citations": answer.citations,
            "sources": [s.chunk.ref for s in answer.sources],
            "latency_ms": answer.meta.latency_ms,
            "model": answer.meta.model,
            "escalated": answer.meta.escalated,
            **score(case, answer, gold),
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        added += 1
        print(f"[{system}] {case['id']} {answer.status}", flush=True)
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=sorted(SYSTEMS), required=True)
    ap.add_argument("--set", dest="question_set", choices=["main", "hard"], default="main")
    ap.add_argument("--as-of", type=date.fromisoformat, default=AS_OF)
    # the results file, when the same system runs another configuration -
    # app_cascade: the app with LLM_ESCALATION set
    ap.add_argument("--name", help="results file name; default: the system")
    args = ap.parse_args()

    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    cases = select_cases(rows, args.question_set)
    suffix = "" if args.question_set == "main" else f"_{args.question_set}"
    out = RESULTS / f"{args.name or args.system}{suffix}.jsonl"
    try:
        added = asyncio.run(run(args.system, cases, out, args.as_of, gold_text(CORPUS)))
    except LLMUnavailable as e:
        print(f"stopped: {e}\nThe provider is unavailable or the quota is spent; "
              "run the same command again later to continue.", file=sys.stderr)
        sys.exit(2)
    print(f"[{args.system}] {added} new, {len(cases)} in the set -> {out}")


if __name__ == "__main__":
    main()
