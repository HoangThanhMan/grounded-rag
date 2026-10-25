"""Turn several report JSONs into the comparison tables the README needs.

    python -m eval.report reports/runs/2026-10-12-gemini/*.json

Every rate comes with a 95% bootstrap interval: the questions are resampled
with replacement, 10,000 times with a fixed seed, and each rate is recomputed
on every resample from the per-question values the report stores
(`cases[].scores`). With 30 unanswerable questions one question moves a rate by
0.033, so a difference between two configurations means little until the
intervals say so. A report written before the per-question values existed
needs `python -m eval.rejudge --keep-verdicts` first.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

COLUMNS = [
    ("hallucination_rate", "Halluc. ↓"),
    ("correct_abstention", "Correct abst. ↑"),
    ("false_abstention", "False abst. ↓"),
    ("answer_correctness", "Numbers right ↑"),
    ("citation_precision", "Cite prec. ↑"),
    ("llm_calls_per_q", "LLM calls/q"),
    ("latency_p95_ms", "p95 (ms)"),
]
RETRIEVAL_COLUMNS = [
    ("retrieval_recall", "Retr. recall ↑"),
    ("recall_at_1", "Recall@1 ↑"),
    ("recall_at_3", "Recall@3 ↑"),
    ("recall_at_5", "Recall@5 ↑"),
    ("mrr", "MRR ↑"),
]
LAYERS = ["retrieval_floor", "out_of_domain", "model", "guard"]

N_BOOT = 10_000
SEED = 20261012  # fixed: the interval is part of the result and must reproduce
LEVEL = 0.95


def intervals(
    scores: list[dict], keys: list[str], n_boot: int = N_BOOT, seed: int = SEED,
    level: float = LEVEL,
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap interval for the mean of each key.

    One resample of the questions serves every key, as the questions are what
    varies between benchmarks. A question whose value for a key is None is not
    in that rate's denominator - an answerable question has no
    correct_abstention - so each key averages over what it applies to.
    """
    if not scores:
        return {}
    rng = random.Random(seed)
    n = len(scores)
    values = {k: [s.get(k) for s in scores] for k in keys}
    stats: dict[str, list[float]] = {k: [] for k in keys}
    for _ in range(n_boot):
        draw = rng.choices(range(n), k=n)
        for k in keys:
            picked = [v for v in (values[k][i] for i in draw) if v is not None]
            if picked:
                stats[k].append(sum(picked) / len(picked))
    tail = (1 - level) / 2
    out = {}
    for k, xs in stats.items():
        if not xs:
            continue
        xs.sort()
        lo = xs[int(tail * len(xs))]
        hi = xs[min(len(xs) - 1, int((1 - tail) * len(xs)))]
        out[k] = (round(lo, 4), round(hi, 4))
    return out


def cell(metrics: dict, ci: dict[str, tuple[float, float]], key: str) -> str:
    value = metrics.get(key, "-")
    if key in ci:
        lo, hi = ci[key]
        return f"{value} [{lo:.2f}, {hi:.2f}]"
    return str(value)


def table(reports: list[dict], cis: list[dict], columns: list[tuple[str, str]]) -> None:
    print("| Configuration | " + " | ".join(c[1] for c in columns) + " |")
    print("|" + "---|" * (len(columns) + 1))
    for data, ci in zip(reports, cis, strict=True):
        cells = [cell(data["metrics"], ci, k) for k, _ in columns]
        print(f"| {data['config']} | " + " | ".join(cells) + " |")


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:] if not p.endswith(".ragas.json")]
    if not paths:
        raise SystemExit("usage: python -m eval.report reports/runs/<run>/*.json")
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    rate_keys = [k for k, _ in COLUMNS + RETRIEVAL_COLUMNS
                 if k not in ("llm_calls_per_q", "latency_p95_ms")]
    cis = []
    for path, data in zip(paths, reports, strict=True):
        scores = [c["scores"] for c in data["cases"] if "scores" in c]
        if len(scores) < len(data["cases"]):
            print(f"[warn] {path}: no per-question scores, so no intervals; "
                  "run `python -m eval.rejudge --keep-verdicts` on it", file=sys.stderr)
            scores = []
        cis.append(intervals(scores, rate_keys))

    print(f"Rates with {LEVEL:.0%} bootstrap intervals ({N_BOOT:,} resamples of the questions).\n")
    table(reports, cis, COLUMNS)
    print()
    table(reports, cis, RETRIEVAL_COLUMNS)

    # Which layer of defence caught the unanswerable questions.
    print("\n| Configuration | " + " | ".join(LAYERS) + " |")
    print("|" + "---|" * (len(LAYERS) + 1))
    for data in reports:
        layers = data["metrics"].get("correct_abstention_by_layer", {})
        print(f"| {data['config']} | " + " | ".join(str(layers.get(k, 0)) for k in LAYERS) + " |")


if __name__ == "__main__":
    main()
