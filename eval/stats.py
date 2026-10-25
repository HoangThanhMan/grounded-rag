"""The statistics behind every comparison the README makes.

With 240 test questions a rate moves by 0.004 per question and a 95% interval
around 0.15 is still about ±0.045, so a number on its own says little. Every
function here works on per-question values, so it runs on saved reports
without the corpus or a model:

  intervals       percentile bootstrap for the mean of each rate, and for p95
  paired          the same questions under two configurations: the difference,
                  its bootstrap interval, a two-sided bootstrap p, and McNemar's
                  exact p when the values are 0/1
  risk_coverage   sweep a confidence score (the guard's weakest claim, or the
                  best retrieval score), trade answered share against the
                  hallucination rate among what is answered; AURC is the area
  over_seeds      mean ± sd of a metric across repeated runs
  cohen_kappa     agreement beyond chance between two labelings
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence

N_BOOT = 10_000
SEED = 20261012  # fixed: the interval is part of the result and must reproduce
LEVEL = 0.95


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, the definition the reports use for p95."""
    s = sorted(values)
    return s[min(int(q * len(s)), len(s) - 1)]


def _bounds(stats: list[float], level: float) -> tuple[float, float]:
    stats.sort()
    tail = (1 - level) / 2
    return (round(stats[int(tail * len(stats))], 4),
            round(stats[min(len(stats) - 1, int((1 - tail) * len(stats)))], 4))


def intervals(
    scores: list[dict], keys: list[str], n_boot: int = N_BOOT, seed: int = SEED,
    level: float = LEVEL, percentiles: dict[str, tuple[str, float]] | None = None,
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap interval for the mean of each key over questions.

    One resample of the questions serves every key, as the questions are what
    varies between benchmarks. A question whose value for a key is None is not
    in that rate's denominator - an answerable question has no
    correct_abstention - so each key averages over what it applies to.
    `percentiles` adds intervals for a percentile of another key, e.g.
    {"latency_p95_ms": ("latency_ms", 0.95)}.
    """
    if not scores:
        return {}
    percentiles = percentiles or {}
    rng = random.Random(seed)
    n = len(scores)
    values = {k: [s.get(k) for s in scores] for k in keys}
    pvalues = {name: [s.get(src) for s in scores] for name, (src, _) in percentiles.items()}
    stats: dict[str, list[float]] = {k: [] for k in [*keys, *percentiles]}
    for _ in range(n_boot):
        draw = rng.choices(range(n), k=n)
        for k in keys:
            picked = [v for v in (values[k][i] for i in draw) if v is not None]
            if picked:
                stats[k].append(sum(picked) / len(picked))
        for name, (_, q) in percentiles.items():
            picked = [v for v in (pvalues[name][i] for i in draw) if v is not None]
            if picked:
                stats[name].append(percentile(picked, q))
    return {k: _bounds(xs, level) for k, xs in stats.items() if xs}


def mcnemar_p(a: Sequence[float], b: Sequence[float]) -> float:
    """Exact two-sided McNemar p for paired 0/1 outcomes: a binomial test on
    the discordant pairs, the only questions that tell the two apart."""
    only_a = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    only_b = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return round(min(1.0, 2 * tail), 4)


def paired(
    a: Sequence[float], b: Sequence[float], n_boot: int = N_BOOT, seed: int = SEED,
    level: float = LEVEL,
) -> dict:
    """a, b: one value per question, the SAME questions in the same order.

    The difference is a - b. p_boot is two-sided: twice the share of resampled
    differences on the far side of zero from the observed one.
    """
    if len(a) != len(b) or not a:
        raise ValueError("paired values for the same, non-empty set of questions")
    d = [x - y for x, y in zip(a, b, strict=True)]
    observed = sum(d) / len(d)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        draw = rng.choices(d, k=len(d))
        boots.append(sum(draw) / len(draw))
    lo, hi = _bounds(boots, level)
    if observed == 0:
        p_boot = 1.0
    else:
        across = sum(1 for x in boots if (x <= 0 if observed > 0 else x >= 0))
        p_boot = min(1.0, 2 * across / n_boot)
    out = {"n": len(d), "diff": round(observed, 4), "ci": (lo, hi), "p_boot": round(p_boot, 4)}
    if all(v in (0, 1) for v in (*a, *b)):
        out["p_mcnemar"] = mcnemar_p(a, b)
    return out


def risk_coverage(
    cases: list[dict], confidence: Callable[[dict], float | None],
    hallucinated: Callable[[dict], bool | None],
) -> dict:
    """Answer only when confidence >= t; sweep t over every observed value.

    coverage(t) = answered answerable questions kept / answerable questions
    risk(t)     = hallucinated among all answers kept (None labels left out)
    AURC        = area under risk over coverage, trapezoid, from the lowest
                  coverage reached up to the highest. Lower is better.
    """
    answerable = sum(1 for c in cases if c["type"] == "answerable")
    answered = [(confidence(c), c) for c in cases if c["status"] in ("answered", "partial")]
    answered = [(s, c) for s, c in answered if s is not None]
    points = []
    for t in sorted({s for s, _ in answered}, reverse=True):
        kept = [c for s, c in answered if s >= t]
        labels = [hallucinated(c) for c in kept]
        labels = [x for x in labels if x is not None]
        if not labels:
            continue
        coverage = sum(1 for c in kept if c["type"] == "answerable") / max(answerable, 1)
        points.append({"threshold": round(t, 4), "coverage": round(coverage, 4),
                       "risk": round(sum(labels) / len(labels), 4), "kept": len(kept)})
    points.sort(key=lambda p: (p["coverage"], -p["threshold"]))
    aurc = 0.0
    for p, q in zip(points, points[1:], strict=False):
        aurc += (q["coverage"] - p["coverage"]) * (p["risk"] + q["risk"]) / 2
    return {"points": points, "aurc": round(aurc, 4)}


def guard_confidence(case: dict) -> float | None:
    """How sure the guard would be: the weakest claim's entailment."""
    scores = [c["entailment"] for c in case.get("claims", []) if c.get("entailment") is not None]
    return min(scores) if scores else None


def floor_confidence(case: dict) -> float | None:
    """How sure retrieval was: the best rerank score among the sources."""
    scores = [s["score"] for s in case.get("sources", [])]
    return max(scores) if scores else None


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Agreement beyond chance between two labelings of the same items."""
    if len(a) != len(b) or not a:
        raise ValueError("two labelings of the same, non-empty set of items")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa = {k: list(a).count(k) for k in set(a)}
    pb = {k: list(b).count(k) for k in set(b)}
    expected = sum(pa.get(k, 0) * pb.get(k, 0) for k in set(pa) | set(pb)) / n**2
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 4)


def over_seeds(values: Sequence[float]) -> tuple[float, float]:
    """mean and sample standard deviation of a metric across repeated runs."""
    if len(values) < 2:
        return (round(values[0], 4) if values else 0.0, 0.0)
    return (round(statistics.fmean(values), 4), round(statistics.stdev(values), 4))
