"""Thirty answers graded by hand - the check on the measuring instrument.

    python scripts/hand_grade.py sample reports/baseline.json reports/full.json ...
    # fill in "grade" for every answer: correct | partly | wrong
    python scripts/hand_grade.py score

The benchmark's hallucination number comes from the same NLI model the guard
uses, so it cannot tell us when that model is wrong. A person reading the answer
next to the gold clause can. `sample` draws answers the pipeline actually gave
(answered or partial) from every report, spread across configurations, with a
fixed seed; `score` sets the hand grades against the instrument's verdict.

Grades:
  correct - every sentence is right by the law, nothing important missing
  partly  - nothing wrong, but part of the question is left unanswered
  wrong   - at least one sentence states something the law does not say
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

SHEET = Path("reports/hand-graded.json")
N = 30
SEED = 17


def sample(paths: list[Path]) -> None:
    rng = random.Random(SEED)
    pools = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        answered = [c for c in report["cases"] if c["status"] in ("answered", "partial")]
        rng.shuffle(answered)
        pools.append((report["config"], answered))
    rows, seen = [], set()
    while len(rows) < N and any(pool for _, pool in pools):
        for config, pool in pools:
            while pool:
                case = pool.pop()
                if (config, case["id"]) in seen:
                    continue
                seen.add((config, case["id"]))
                rows.append({
                    "config": config, "id": case["id"], "type": case["type"],
                    "question": case["question"], "gold_answer": case["gold_answer"],
                    "answer": case["answer"], "status": case["status"],
                    "instrument_hallucinated": case["hallucinated"],
                    "claims": [(c["text"], c["verdict"], c["entailment"]) for c in case["claims"]],
                    "cited": {s["label"]: s["text"] for s in case["sources"]
                              if s["label"] in case["cited"]},
                    "grade": None, "note": "",
                })
                break
            if len(rows) == N:
                break
    SHEET.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} answers -> {SHEET}: fill in every `grade`, then run `score`")


def score() -> None:
    rows = json.loads(SHEET.read_text(encoding="utf-8"))
    missing = [r["id"] for r in rows if r["grade"] not in ("correct", "partly", "wrong")]
    if missing:
        raise SystemExit(f"ungraded: {missing}")
    grades = Counter(r["grade"] for r in rows)
    # the instrument flags an answer; a person says whether it is wrong
    agree = Counter(
        ("flagged" if r["instrument_hallucinated"] else "clean",
         "wrong" if r["grade"] == "wrong" else "not wrong")
        for r in rows
    )
    by_config = {
        config: dict(Counter(r["grade"] for r in rows if r["config"] == config))
        for config in dict.fromkeys(r["config"] for r in rows)
    }
    summary = {
        "n": len(rows),
        "grades": dict(grades),
        "by_config": by_config,
        "instrument_vs_hand": {
            "flagged_and_wrong": agree[("flagged", "wrong")],
            "flagged_but_not_wrong": agree[("flagged", "not wrong")],
            "clean_but_wrong": agree[("clean", "wrong")],
            "clean_and_not_wrong": agree[("clean", "not wrong")],
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    Path("reports/hand-graded.summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "score"])
    ap.add_argument("reports", nargs="*", type=Path)
    args = ap.parse_args()
    if args.step == "sample":
        sample(args.reports)
    else:
        score()


if __name__ == "__main__":
    main()
