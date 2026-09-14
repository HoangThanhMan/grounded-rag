"""Re-score saved reports with the current measuring instrument - no LLM calls.

    python -m eval.rejudge reports/baseline.json reports/full.json

The answers are not regenerated; only the judging is redone: claim verdicts,
gold matching, the metrics. Use it after changing the instrument or the judge
threshold, when free-tier quotas make re-running the pipeline expensive.
Reports are rewritten in place.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.instrument import ClauseIndex, judge_claims
from eval.metrics import Case, Row, aggregate, hallucinated
from eval.report import COLUMNS
from grounded_rag.config import settings
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.types import Answer, AnswerMeta, Chunk, RetrievedChunk, Step

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
    args = ap.parse_args()

    index = ClauseIndex(args.corpus)
    verifier = get_verifier()
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for record in report["cases"]:
            answer = answer_from(record)
            case = Case(id=record["id"], answerable=record["type"] == "answerable",
                        gold_chunks=record["gold_chunks"], type=record["type"],
                        tags=record.get("tags", []))
            row = Row(case=case, answer=answer,
                      judged=judge_claims(answer, verifier, args.judge_threshold, index))
            record["claims"] = [c.model_dump(mode="json") for c in row.judged]
            record["hallucinated"] = hallucinated(row)
            rows.append(row)
        report["metrics"] = aggregate(rows, index.gold_text())
        report["judge"] = {**report.get("judge", {}), "threshold": args.judge_threshold,
                           "instrument": "clause-level premises (eval/instrument.py)"}
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
        m = report["metrics"]
        print(f"{report['config']:9}", {k: m.get(k) for k, _ in COLUMNS})


if __name__ == "__main__":
    main()
