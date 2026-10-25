"""Answers graded by hand - the check on the measuring instrument.

    python scripts/hand_grade.py sample reports/runs/2026-10-12-gemini/*.json
    # fill in "grade" for every answer: correct | partly | wrong
    python scripts/hand_grade.py score

The benchmark's hallucination number comes from the same NLI model the guard
uses, so it cannot tell us when that model is wrong. A person reading the answer
next to the gold clause can. `sample` draws two strata of answers the pipeline
actually gave (answered or partial), with a fixed seed:

  random  - 30 answers spread across configurations: how often the instrument
            misses a wrong answer, on answers as they come
  flagged - every other answer the instrument called hallucinated: how often it
            flags a right one. A flagged answer that the random draw already
            took stays `random`, so that stratum is still a plain random sample

`score` sets the hand grades against the instrument's verdict.

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

SHEET = Path("reports/grading/hand-graded.json")
SUMMARY = SHEET.with_name("hand-graded.summary.json")
N = 30
SEED = 17


def _row(config: str, case: dict, stratum: str) -> dict:
    return {
        "stratum": stratum, "config": config, "id": case["id"], "type": case["type"],
        "question": case["question"], "gold_answer": case["gold_answer"],
        "answer": case["answer"], "status": case["status"],
        "instrument_hallucinated": case["hallucinated"],
        "claims": [(c["text"], c["verdict"], c["entailment"]) for c in case["claims"]],
        "cited": {s["label"]: s["text"] for s in case["sources"] if s["label"] in case["cited"]},
        "grade": None, "note": "",
    }


def draw(reports: list[dict], n: int = N, seed: int = SEED) -> list[dict]:
    """The sheet: `n` random answers round-robin across reports, then every
    remaining answer the instrument flagged, in report order."""
    rng = random.Random(seed)
    pools = []
    for report in reports:
        answered = [c for c in report["cases"] if c["status"] in ("answered", "partial")]
        rng.shuffle(answered)
        pools.append((report["config"], answered))
    rows, seen = [], set()
    while len(rows) < n and any(pool for _, pool in pools):
        for config, pool in pools:
            while pool:
                case = pool.pop()
                if (config, case["id"]) in seen:
                    continue
                seen.add((config, case["id"]))
                rows.append(_row(config, case, "random"))
                break
            if len(rows) == n:
                break
    for report in reports:
        for case in report["cases"]:
            if case["hallucinated"] and (report["config"], case["id"]) not in seen:
                seen.add((report["config"], case["id"]))
                rows.append(_row(report["config"], case, "flagged"))
    return rows


def sample(paths: list[Path], force: bool = False) -> None:
    if SHEET.exists() and not force:
        graded = [r for r in json.loads(SHEET.read_text(encoding="utf-8")) if r["grade"]]
        if graded:
            raise SystemExit(f"{SHEET} already has {len(graded)} grades; "
                             "pass --force to draw a new sheet over them")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    rows = draw(reports)
    SHEET.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    strata = Counter(r["stratum"] for r in rows)
    print(f"{len(rows)} answers ({dict(strata)}) -> {SHEET}: "
          "fill in every `grade`, then run `score`")


def score() -> None:
    rows = json.loads(SHEET.read_text(encoding="utf-8"))
    missing = [f"{r['config']}:{r['id']}" for r in rows
               if r["grade"] not in ("correct", "partly", "wrong")]
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
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "score"])
    ap.add_argument("reports", nargs="*", type=Path)
    ap.add_argument("--force", action="store_true", help="sample: overwrite a graded sheet")
    args = ap.parse_args()
    if args.step == "sample":
        sample(args.reports, args.force)
    else:
        score()


if __name__ == "__main__":
    main()
