"""What does the retrieval floor cost, and what does it buy?

`min_score` decides whether the LLM is called at all. Set it too high and
answerable questions are refused before anything is generated; too low and the
40 unanswerable questions reach the model, which is where invention starts.
That trade is measurable, and retrieval is deterministic - so one pass over the
corpus scores every threshold at once, with no LLM calls.

    python scripts/sweep_floor.py --out reports/floor-sweep.json

Reported per threshold, over the labelled dataset:

    reach_llm            answerable questions that get past the floor
    gold_survives        answerable questions whose gold clause is above it
    floor_blocks         unanswerable questions the floor stops for free

`gold_survives` is the honest one. A question can clear the floor on an
irrelevant chunk: the LLM is then called with the wrong passage, which is worse
than refusing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from eval.run import load_cases  # noqa: E402
from grounded_rag.config import RunConfig  # noqa: E402
from grounded_rag.retrieval.corrective import search  # noqa: E402

THRESHOLDS = [0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/full.yaml", type=Path)
    ap.add_argument("--dataset", default="eval/dataset/questions.jsonl", type=Path)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    config = RunConfig.from_yaml(args.config)
    cases = list(load_cases(args.dataset))
    print(f"{len(cases)} questions, chunker={config.retrieval.chunker}, "
          f"current min_score={config.retrieval.min_score}\n", flush=True)

    rows = []
    for i, case in enumerate(cases, 1):
        hits = search(case["question"], config, args.as_of)
        gold = set(case.get("gold_chunks", []))
        rows.append({
            "id": case["id"],
            "answerable": case["answerable"],
            "type": case.get("type"),
            "top_score": round(max((s for _, s in hits), default=0.0), 4),
            # best score among the clauses actually labelled as the answer
            "gold_score": round(max((s for c, s in hits if c.ref in gold), default=0.0), 4),
        })
        print(f"[{i}/{len(cases)}] {case['id']} top={rows[-1]['top_score']:.3f} "
              f"gold={rows[-1]['gold_score']:.3f}", flush=True)

    ans = [r for r in rows if r["answerable"]]
    una = [r for r in rows if not r["answerable"]]
    curve = []
    for t in THRESHOLDS:
        curve.append({
            "min_score": t,
            "reach_llm": round(sum(r["top_score"] >= t for r in ans) / len(ans), 4),
            "gold_survives": round(sum(r["gold_score"] >= t for r in ans) / len(ans), 4),
            "floor_blocks": round(sum(r["top_score"] < t for r in una) / len(una), 4),
        })

    print(f"\n{'min_score':>10}{'reach_llm':>12}{'gold_survives':>15}{'floor_blocks':>14}")
    for c in curve:
        print(f"{c['min_score']:>10}{c['reach_llm']:>12}{c['gold_survives']:>15}"
              f"{c['floor_blocks']:>14}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"curve": curve, "cases": rows},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
