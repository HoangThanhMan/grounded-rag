"""Run the benchmark for one configuration.

    python -m eval.run --config configs/full.yaml --out reports/full.json

Exits non-zero when a threshold is breached, which is what makes it usable
as a CI gate rather than a report you have to read.

The report keeps every case in full - question, contexts, answer, judged
claims, steps - because error analysis and eval/ragas_eval.py both need them.

With --resume every finished case is appended to <out>.partial.jsonl as it
completes, and a rerun skips the cases already there - a free-tier quota that
runs out at question 150 costs a restart, not the first 150 answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from eval.instrument import ClauseIndex, judge_claims
from eval.metrics import Case, Row, aggregate, case_scores, hallucinated
from eval.rejudge import answer_from
from grounded_rag.config import RunConfig, settings
from grounded_rag.generation.citation import extract_citations
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.ingest.pipeline import ingest
from grounded_rag.retrieval import cache
from grounded_rag.retrieval.corrective import search
from grounded_rag.service import answer_question
from grounded_rag.types import Claim

# Outer retry, on top of the client's own: rides out an outage that lasts
# longer than one question.
_CASE_RETRIES = 3
_CASE_BACKOFF_S = 15.0

DEFAULT_GATES = {"hallucination_rate": 0.10, "false_abstention": 0.15}
QUOTA_EXIT = 3


class ProviderExhausted(RuntimeError):
    """Too many questions in a row failed on the provider: a spent daily quota,
    not a flaky call. The checkpoint keeps every finished case."""


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def run(
    config: RunConfig,
    dataset: Path,
    index: ClauseIndex,
    judge_threshold: float,
    as_of: date,
    split: str = "all",
    checkpoint: Path | None = None,
    seed: int | None = None,
    max_consecutive_errors: int = 0,
) -> dict:
    # The measuring instrument: same verifier, same threshold, every config.
    verifier = get_verifier()
    # Load every model before the clock starts, so the first question is not
    # charged for it. Run each configuration in its own process as well
    # (`make eval-all` does): the NLI cache would otherwise flatter whichever
    # configuration runs second.
    search("khởi động", config, as_of)
    verifier.entailment("khởi động", "khởi động")
    done = _resume(checkpoint)
    rows: dict[str, Row] = {}
    records: dict[str, dict] = {}
    errored = []
    gold_text = index.gold_text()
    order = []
    streak = 0
    for raw in load_cases(dataset):
        # dev questions calibrate τ (scripts/calibrate_tau.py); a number
        # reported on them would be scored on its own training data
        if split != "all" and raw.get("split", "test") != split:
            continue
        case = Case(
            id=raw["id"],
            answerable=raw["answerable"],
            gold_chunks=raw.get("gold_chunks", []),
            type=raw.get("type", "answerable"),
            tags=raw.get("tags", []),
            gold_answer=raw.get("gold_answer"),
        )
        order.append(raw["id"])
        if raw["id"] in done:
            record = done[raw["id"]]
            judged = [Claim.model_validate(c) for c in record["claims"]]
            rows[raw["id"]] = Row(case=case, answer=answer_from(record), judged=judged)
            records[raw["id"]] = record
            continue
        try:
            # a temporal question is asked on its own date; the run's as_of is
            # the date for every other question
            on = date.fromisoformat(raw["as_of"]) if raw.get("as_of") else as_of
            answer = await _answer_with_retries(raw["question"], config, on)
        except LLMUnavailable as e:
            # A provider outage is not a property of the configuration. Losing
            # an hour of benchmark to one 503 is worse than reporting n < 100,
            # so the case is recorded as errored and the run continues.
            print(f"[error] {raw['id']}: {e}", flush=True)
            errored.append({"id": raw["id"], "error": str(e)[:300]})
            streak += 1
            if max_consecutive_errors and streak >= max_consecutive_errors:
                raise ProviderExhausted(f"{streak} questions in a row failed: {e}") from e
            continue
        streak = 0
        judged = judge_claims(answer, verifier, judge_threshold, index)
        row = Row(case=case, answer=answer, judged=judged)
        rows[raw["id"]] = row
        records[raw["id"]] = _case_record(raw, row, gold_text)
        if checkpoint:
            with checkpoint.open("a", encoding="utf-8") as f:
                f.write(json.dumps(records[raw["id"]], ensure_ascii=False) + "\n")

    finished = [i for i in order if i in rows]
    return {
        "config": config.name,
        "dataset": str(dataset),
        "split": split,
        "as_of": as_of.isoformat(),
        # the model that wrote the answers - a report without it cannot be
        # compared with anything, and the conclusions flip between models
        "generator": {"provider": settings.llm_provider, "model": settings.llm_model,
                      "temperature": config.generation.temperature},
        "seed": seed,
        # a cached search costs nothing, so latency is not comparable across
        # configurations of a run that used the cache
        "retrieval_cache": cache.enabled(),
        "judge": {
            "verifier": "mock" if settings.llm_provider == "mock" else settings.nli_model,
            "threshold": judge_threshold,
        },
        "metrics": aggregate([rows[i] for i in finished], gold_text),
        "errored": errored,
        "cases": [records[i] for i in finished],
    }


def _resume(checkpoint: Path | None) -> dict[str, dict]:
    if not checkpoint or not checkpoint.exists():
        return {}
    done = {}
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            done[record["id"]] = record
    print(f"[resume] {len(done)} cases from {checkpoint}")
    return done


async def _answer_with_retries(question: str, config: RunConfig, as_of: date):
    """The client already retries inside one call. This is the outer loop, for
    an outage that outlives a single question."""
    for attempt in range(_CASE_RETRIES + 1):
        try:
            return await answer_question(question, config, as_of=as_of)
        except LLMUnavailable:
            if attempt == _CASE_RETRIES:
                raise
            await asyncio.sleep(_CASE_BACKOFF_S * 2**attempt)
    raise AssertionError("unreachable")


def _case_record(raw: dict, row: Row, gold_text: dict[str, str]) -> dict:
    a = row.answer
    return {
        "id": row.case.id,
        "type": row.case.type,
        "as_of": raw.get("as_of"),
        "tags": row.case.tags,
        "question": raw["question"],
        "gold_answer": raw.get("gold_answer"),
        "gold_chunks": row.case.gold_chunks,
        "status": a.status,
        "abstain_reason": a.meta.abstain_reason,
        "answer": a.answer,
        "hallucinated": hallucinated(row),
        # what every rate in `metrics` is a mean of; eval/report.py bootstraps these
        "scores": case_scores(row, gold_text),
        "claims": [c.model_dump(mode="json") for c in row.judged],
        # what the pipeline's own guard decided, dropped claims included - the
        # only place its false positives (correct claims it removed) show up
        "guard_claims": [c.model_dump(mode="json") for c in a.claims],
        "cited": extract_citations(a.answer),
        "sources": [
            {"label": s.label, "ref": s.chunk.ref, "score": s.score, "text": s.chunk.text,
             "article": s.chunk.article, "clause": s.chunk.clause}
            for s in a.sources
        ],
        "latency_ms": a.meta.latency_ms,
        "tokens": a.meta.tokens,
        "llm_calls": a.meta.llm_calls,
        "cost_usd": a.meta.cost_usd,
        "steps": [s.model_dump(mode="json") for s in a.meta.steps],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dataset", default="eval/dataset/questions.jsonl", type=Path)
    ap.add_argument("--out", default=None)
    ap.add_argument("--gate", action="store_true", help="exit 1 when thresholds are breached")
    ap.add_argument(
        "--ingest",
        default=None,
        type=Path,
        help="index this directory first. Required with the in-memory mock store, "
        "which lives inside one process and is therefore empty at eval time.",
    )
    ap.add_argument(
        "--corpus",
        default=None,
        type=Path,
        help="where gold refs are resolved to text (default: --ingest, else data/corpus)",
    )
    ap.add_argument("--judge-threshold", type=float, default=settings.entailment_threshold)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--resume", action="store_true",
                    help="checkpoint each case to <out>.partial.jsonl and skip finished ones")
    ap.add_argument("--temperature", type=float, help="override the config's temperature")
    ap.add_argument("--seed", type=int, help="label of a repeated run, stored in the report")
    ap.add_argument("--max-consecutive-errors", type=int, default=0,
                    help="stop without a report after this many provider failures in a row "
                         "(exit 3); with --resume the next run carries on")
    ap.add_argument(
        "--split",
        choices=["test", "dev", "all"],
        default="test",
        help="test (default): the questions τ was not calibrated on",
    )
    args = ap.parse_args()

    SAMPLE = Path("eval/dataset/questions.sample.jsonl")
    dataset = args.dataset
    if not dataset.exists():
        dataset = SAMPLE
        print(f"[warn] {args.dataset} not found, falling back to {dataset}")
    # Six questions over an excerpt of one law say whether the pipeline runs,
    # not whether it is good enough to ship. Thresholds need the full dataset
    # against the full corpus.
    on_sample = dataset.name == SAMPLE.name

    config = RunConfig.from_yaml(args.config)
    if args.temperature is not None:
        config.generation.temperature = args.temperature

    # The instrument's threshold comes from the environment, the guard's from
    # the YAML. They are separate on purpose, but a silent divergence makes
    # every number in the report wrong in a way nobody notices.
    print(f"[judge] {settings.nli_model} tau={args.judge_threshold} "
          f"(guard tau={config.guard.entailment_threshold})")
    if abs(args.judge_threshold - config.guard.entailment_threshold) > 1e-9:
        print(f"[warn] judge tau {args.judge_threshold} != guard tau "
              f"{config.guard.entailment_threshold}; set ENTAILMENT_THRESHOLD or "
              f"pass --judge-threshold if that is not intended")

    if args.ingest:
        stats = ingest(args.ingest, config)
        print(f"[ingest] files={stats['files']} chunks={stats['chunks']}")

    index = ClauseIndex(args.corpus or args.ingest or Path("data/corpus"))
    checkpoint = Path(f"{args.out}.partial.jsonl") if args.resume and args.out else None
    if checkpoint:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(
            run(config, dataset, index, args.judge_threshold, args.as_of, args.split,
                checkpoint=checkpoint, seed=args.seed,
                max_consecutive_errors=args.max_consecutive_errors)
        )
    except ProviderExhausted as e:
        print(f"[stop] {e}; resume later with the same command", flush=True)
        raise SystemExit(QUOTA_EXIT) from e

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
        # a report with errored cases keeps its checkpoint, so a rerun retries them
        if checkpoint and checkpoint.exists() and not report["errored"]:
            checkpoint.unlink()

    m = report["metrics"]
    print(f"\n=== {report['config']} (n={m.get('n', 0)}) ===")
    for k, v in m.items():
        print(f"  {k:28} {v}")

    if args.gate and on_sample:
        print("\n[skip] thresholds are not enforced on the sample dataset - "
              "run against eval/dataset/questions.jsonl and the full corpus")
    elif args.gate:
        breached = [k for k, limit in DEFAULT_GATES.items() if m.get(k, 0) > limit]
        if breached:
            print(f"\nFAIL: threshold breached -> {', '.join(breached)}")
            raise SystemExit(1)
        print("\nPASS: all thresholds met")


if __name__ == "__main__":
    main()
