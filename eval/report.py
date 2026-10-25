"""Turn report JSONs into the comparison tables the README needs.

    python -m eval.report reports/runs/2026-10-12-gemini/*.json
    python -m eval.report reports/runs/<matrix>/*/*.json --out summary.md --svg risk.svg

Every table is computed from the per-question values each report stores
(`cases[].scores`), with eval/stats.py:

  rates          95% bootstrap interval on every rate and on p95 latency
  retrieval      recall@k and MRR, same intervals
  paired         two configurations on the same questions: difference, its
                 interval, a two-sided bootstrap p and McNemar's exact p. "A
                 beats B" is claimed when the test chosen by the data type -
                 McNemar for 0/1 values, the bootstrap otherwise - gives p < 0.05
  risk-coverage  AURC when the guard's threshold or the retrieval floor is
                 swept; hallucination read from the LLM judge when the report
                 has been judged (eval/judge.py), else from the NLI instrument -
                 which is circular, and the table says which it used
  seeds          mean ± sd across repeated runs of one configuration

A report written before the per-question values existed needs
`python -m eval.rejudge --keep-verdicts` first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from eval import stats
from eval.stats import N_BOOT, intervals  # noqa: F401 - re-exported for callers

COLUMNS = [
    ("hallucination_rate", "Halluc. ↓"),
    ("judge_hallucination_rate", "Halluc. (judge) ↓"),
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
PAIRED = ["hallucination_rate", "judge_hallucination_rate", "false_abstention",
          "correct_abstention", "answer_correctness"]
DEFAULT_PAIRS = "baseline:threshold,threshold:full,full:agentic,baseline:full"
LAYERS = ["retrieval_floor", "out_of_domain", "model", "guard"]
NOT_RATES = {"llm_calls_per_q", "latency_p95_ms"}


def name(data: dict) -> str:
    gen = (data.get("generator") or {}).get("model", "?").split("/")[-1]
    seed = f" s{data['seed']}" if data.get("seed") is not None else ""
    return f"{data['config']} · {gen}{seed}"


def cell(metrics: dict, ci: dict[str, tuple[float, float]], key: str) -> str:
    value = metrics.get(key, "-")
    if key in ci:
        lo, hi = ci[key]
        if key == "latency_p95_ms":
            return f"{value} [{lo:.0f}, {hi:.0f}]"
        return f"{value} [{lo:.2f}, {hi:.2f}]"
    return str(value)


def table(rows: list[tuple[str, dict, dict]], columns: list[tuple[str, str]]) -> list[str]:
    present = [(k, h) for k, h in columns if any(k in m for _, m, _ in rows)]
    out = ["| Configuration | " + " | ".join(h for _, h in present) + " |",
           "|" + "---|" * (len(present) + 1)]
    out += [f"| {label} | " + " | ".join(cell(m, ci, k) for k, _ in present) + " |"
            for label, m, ci in rows]
    return out


def scores_of(data: dict) -> list[dict]:
    rows = []
    for c in data["cases"]:
        s = dict(c.get("scores") or {})
        s["latency_ms"] = c.get("latency_ms")
        rows.append(s)
    return rows


def paired_table(reports: list[dict], pairs: str) -> list[str]:
    groups: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for data in reports:
        key = ((data.get("generator") or {}).get("model"), data.get("seed"))
        groups[key][data["config"]] = data
    out = ["| A vs B | Metric | n | A − B [95% CI] | p (bootstrap) | p (McNemar) |",
           "|---|---|---|---|---|---|"]
    for (model, seed), by_config in groups.items():
        for pair in pairs.split(","):
            a_name, b_name = pair.split(":")
            if a_name not in by_config or b_name not in by_config:
                continue
            a = {c["id"]: c.get("scores") or {} for c in by_config[a_name]["cases"]}
            b = {c["id"]: c.get("scores") or {} for c in by_config[b_name]["cases"]}
            for metric in PAIRED:
                ids = [i for i in a if i in b and a[i].get(metric) is not None
                       and b[i].get(metric) is not None]
                if not ids:
                    continue
                r = stats.paired([a[i][metric] for i in ids], [b[i][metric] for i in ids])
                tag = f" ({model.split('/')[-1]}{f' s{seed}' if seed is not None else ''})"
                lo, hi = r["ci"]
                # one test decides, chosen by the data type, never by the result:
                # McNemar's exact test for 0/1 outcomes, the bootstrap otherwise
                mark = " **" if r.get("p_mcnemar", r["p_boot"]) < 0.05 else ""
                out.append(f"| {a_name} vs {b_name}{tag} | {metric} | {r['n']} | "
                           f"{r['diff']:+.3f} [{lo:+.2f}, {hi:+.2f}]{mark} | {r['p_boot']} | "
                           f"{r.get('p_mcnemar', '-')} |")
    return out


def hallucination_label(case: dict) -> bool | None:
    if "judge" in case:
        return case["judge"].get("hallucinated")
    return case.get("hallucinated")


def coverage_table(reports: list[dict]) -> tuple[list[str], dict[str, dict]]:
    out = ["| Configuration | AURC, guard τ swept ↓ | AURC, floor swept ↓ "
           "| Hallucination read from |", "|---|---|---|---|"]
    curves = {}
    for data in reports:
        judged = any("judge" in c for c in data["cases"])
        guard = stats.risk_coverage(data["cases"], stats.guard_confidence, hallucination_label)
        floor = stats.risk_coverage(data["cases"], stats.floor_confidence, hallucination_label)
        curves[name(data)] = guard
        out.append(f"| {name(data)} | {guard['aurc']} | {floor['aurc']} | "
                   f"{'LLM judge' if judged else 'NLI instrument (circular)'} |")
    return out, curves


def seeds_table(reports: list[dict]) -> list[str]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for data in reports:
        groups[(data["config"], (data.get("generator") or {}).get("model"))].append(data)
    repeated = {k: v for k, v in groups.items() if len(v) > 1}
    if not repeated:
        return []
    keys = [k for k, _ in COLUMNS if k not in NOT_RATES]
    out = ["| Configuration | runs | " + " | ".join(keys) + " |",
           "|" + "---|" * (len(keys) + 2)]
    for (config, model), runs in repeated.items():
        cells = []
        for k in keys:
            vals = [r["metrics"][k] for r in runs if k in r["metrics"]]
            mean, sd = stats.over_seeds(vals) if vals else (None, None)
            cells.append("-" if mean is None else f"{mean} ± {sd}")
        label = f"{config} · {model.split('/')[-1]}"
        out.append(f"| {label} | {len(runs)} | " + " | ".join(cells) + " |")
    return out


def svg(curves: dict[str, dict]) -> str:
    """Risk against coverage, one line per run, light and dark."""
    w, h, left, right, top, bottom = 640, 380, 56, 190, 48, 48
    pw, ph = w - left - right, h - top - bottom
    top_risk = max([p["risk"] for c in curves.values() for p in c["points"]] + [0.05])
    x = lambda v: left + v * pw  # noqa: E731
    y = lambda v: top + (1 - v / top_risk) * ph  # noqa: E731
    colors = ["#2a78d6", "#eb6834", "#1f9d6b", "#8a5cd1", "#c2410c", "#0e7490"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        'font-family="system-ui, sans-serif" font-size="12" role="img" '
        'aria-label="Risk against coverage as the guard threshold moves">',
        "<style>.bg{fill:#fcfcfb}.ink{fill:#0b0b0b}.muted{fill:#52514e}.grid{stroke:#e4e3de}"
        "@media (prefers-color-scheme: dark){.bg{fill:#1a1a19}.ink{fill:#fff}"
        ".muted{fill:#c3c2b7}.grid{stroke:#383835}}</style>",
        f'<rect class="bg" width="{w}" height="{h}" rx="8"/>',
        f'<text class="ink" x="{left}" y="24" font-size="14" font-weight="600">'
        "Risk–coverage as the guard threshold moves</text>",
        f'<text class="muted" x="{left}" y="40">coverage: answerable questions answered · '
        "risk: hallucinated among answers kept</text>",
    ]
    for i in range(5):
        v = top_risk * i / 4
        parts.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y(v)}" y2="{y(v)}"/>')
        parts.append(f'<text class="muted" x="{left - 8}" y="{y(v) + 4}" text-anchor="end">'
                     f"{v:.0%}</text>")
    for v in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<text class="muted" x="{x(v)}" y="{top + ph + 18}" text-anchor="middle">'
                     f"{v:.0%}</text>")
    for k, (label, curve) in enumerate(curves.items()):
        pts = [(p["coverage"], p["risk"]) for p in curve["points"]]
        if not pts:
            continue
        color = colors[k % len(colors)]
        path = " ".join(f"{x(c):.1f},{y(r):.1f}" for c, r in pts)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{path}"/>')
        c, r = pts[-1]
        parts.append(f'<text fill="{color}" x="{x(c) + 8:.1f}" y="{y(r) + 4 + 12 * (k % 3):.1f}">'
                     f"{label} (AURC {curve['aurc']})</text>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render(reports: list[dict], paths: list[Path], pairs: str) -> tuple[str, dict]:
    rate_keys = [k for k, _ in COLUMNS + RETRIEVAL_COLUMNS if k not in NOT_RATES]
    rows = []
    for path, data in zip(paths, reports, strict=True):
        scores = scores_of(data)
        if not all(c.get("scores") for c in data["cases"]):
            print(f"[warn] {path}: no per-question scores, so no intervals; "
                  "run `python -m eval.rejudge --keep-verdicts` on it", file=sys.stderr)
            ci = {}
        else:
            ci = intervals(scores, rate_keys,
                           percentiles={"latency_p95_ms": ("latency_ms", 0.95)})
        rows.append((name(data), data["metrics"], ci))
    lines = [f"Rates with 95% bootstrap intervals ({N_BOOT:,} resamples of the questions).", ""]
    if any(data.get("retrieval_cache") for data in reports):
        lines += ["p95 is not comparable across configurations here: the retrieval cache was "
                  "on, so only the first configuration paid for retrieval.", ""]
    lines += table(rows, COLUMNS) + [""] + table(rows, RETRIEVAL_COLUMNS) + [""]
    lines += ["Which layer of defence caught the unanswerable questions:", "",
              "| Configuration | " + " | ".join(LAYERS) + " |", "|" + "---|" * (len(LAYERS) + 1)]
    for data in reports:
        layers = data["metrics"].get("correct_abstention_by_layer", {})
        caught = " | ".join(str(layers.get(k, 0)) for k in LAYERS)
        lines.append(f"| {name(data)} | {caught} |")
    paired_lines = paired_table(reports, pairs)
    if len(paired_lines) > 2:
        lines += ["", "Paired comparisons on the same questions (** = p < 0.05, McNemar for "
                  "0/1 values, bootstrap otherwise):", ""] + paired_lines
    cov_lines, curves = coverage_table(reports)
    lines += ["", "Risk–coverage:", ""] + cov_lines
    seed_lines = seeds_table(reports)
    if seed_lines:
        lines += ["", "Across repeated runs (mean ± sd):", ""] + seed_lines
    return "\n".join(lines) + "\n", curves


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--pairs", default=DEFAULT_PAIRS, help="a:b,c:d - configurations to compare")
    ap.add_argument("--out", type=Path, help="also write the tables here")
    ap.add_argument("--svg", type=Path, help="write the risk-coverage figure here")
    args = ap.parse_args()
    paths = [p for p in args.reports if not p.name.endswith((".ragas.json", ".partial.json"))]
    if not paths:
        raise SystemExit("usage: python -m eval.report reports/runs/<run>/*.json")
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    text, curves = render(reports, paths, args.pairs)
    print(text, end="")
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.svg:
        args.svg.write_text(svg(curves), encoding="utf-8")


if __name__ == "__main__":
    main()
