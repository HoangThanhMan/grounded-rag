"""Re-score saved reports with the current measuring instrument - no LLM calls.

    python -m eval.rejudge reports/baseline.json reports/full.json
    python -m eval.rejudge --keep-verdicts reports/runs/2026-10-12-gemini/*.json

The answers are not regenerated; only the judging is redone: claim verdicts,
gold matching, the metrics. Use it after changing the instrument or the judge
threshold, when free-tier quotas make re-running the pipeline expensive.
`--keep-verdicts` reuses the claim verdicts already in the report and only
recomputes the metrics - for a new metric on a published run, without the NLI
model and without moving a number that is already quoted. Reports are
rewritten in place.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.instrument import ClauseIndex, judge_claims
from eval.metrics import Case, Row, aggregate, case_scores, hallucinated
from eval.report import COLUMNS
from grounded_rag.config import settings
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.types import Answer, AnswerMeta, Chunk, Claim, RetrievedChunk, Step

_REF = re.compile(r"^(?P<doc>[^:]+):(?P<article>Điều \d+[a-z]?)(?::(?P<clause>\d+))?$")


def answer_from(record: dict) -> Answer:
    sources = []
    for s in record["sources"]:
        m = _REF.match(s["ref"])
        article = s.get("article") or (m.group("article") if m else None)
        clause = s.get("clause")
        if not clause and m and m.group("clause"):
            clause = f"Khoản {m.group('clause')}"
        doc_id = m.group("doc") if m else s["ref"].split(":")[0]
        chunk = Chunk(
            chunk_id=s["ref"], doc_id=doc_id, text=s["text"], article=article, clause=clause
        )
        sources.append(RetrievedChunk(chunk=chunk, score=s["score"], label=s["label"]))
    meta = AnswerMeta(
        latency_ms=record["latency_ms"],
        tokens=record["tokens"],
        llm_calls=record["llm_calls"],
        cost_usd=record.get("cost_usd", 0.0),
        abstain_reason=record.get("abstain_reason"),
        steps=[Step.model_validate(s) for s in record.get("steps", [])],
    )
    return Answer(answer=record["answer"], status=record["status"], sources=sources, meta=meta)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ap.add_argument("--judge-threshold", type=float, default=settings.entailment_threshold)
    ap.add_argument("--keep-verdicts", action="store_true",
                    help="reuse the stored claim verdicts; recompute only the metrics")
    args = ap.parse_args()

    index = ClauseIndex(args.corpus)
    gold_text = index.gold_text()
    verifier = None if args.keep_verdicts else get_verifier()
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for record in report["cases"]:
            answer = answer_from(record)
            case = Case(id=record["id"], answerable=record["type"] == "answerable",
                        gold_chunks=record["gold_chunks"], type=record["type"],
                        tags=record.get("tags", []), gold_answer=record.get("gold_answer"))
            if args.keep_verdicts:
                judged = [Claim.model_validate(c) for c in record["claims"]]
            else:
                judged = judge_claims(answer, verifier, args.judge_threshold, index)
            row = Row(case=case, answer=answer, judged=judged)
            record["claims"] = [c.model_dump(mode="json") for c in row.judged]
            record["hallucinated"] = hallucinated(row)
            record["scores"] = case_scores(row, gold_text)
            rows.append(row)
        report["metrics"] = aggregate(rows, gold_text)
        if not args.keep_verdicts:
            report["judge"] = {**report.get("judge", {}), "threshold": args.judge_threshold,
                               "instrument": "clause-level premises (eval/instrument.py)"}
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
        m = report["metrics"]
        print(f"{report['config']:9}", {k: m.get(k) for k, _ in COLUMNS})


if __name__ == "__main__":
    main()
