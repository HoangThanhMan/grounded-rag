"""Calibrate the guard's entailment threshold τ on the dev split.

    python scripts/calibrate_tau.py collect      # LLM + models -> reports/tau-dev-claims.json
    # label every claim by hand: "grounded": true | false
    python scripts/calibrate_tau.py sweep        # -> reports/tau-sweep.json, assets/tau-curve.svg
    python scripts/calibrate_tau.py rescore      # after a verifier change, then sweep again

`collect` answers the 20 dev questions with the `full` and the `baseline`
retrieval and the guard off, so every claim the model writes is kept - the
baseline has no retrieval floor, so the model also answers the unanswerable
questions, which is where ungrounded claims come from - and scores each claim twice:
against the sources it cites, and against the best other retrieved source (the
guard relabels a claim to that one when it clears τ - guard/policy.py). The
file it writes is the labelling sheet: premises are included so a label can be
decided by reading, not by trusting the score.

`sweep` simulates the guard at each τ from those two scores and the hand labels:
how many ungrounded claims it blocks, how many grounded ones it blocks by
mistake, and on how many answerable questions nothing survives. No LLM call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from grounded_rag.config import RunConfig
from grounded_rag.guard.claim_splitter import split_claims
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.service import answer_question

DATASET = Path("eval/dataset/questions.jsonl")
CLAIMS = Path("reports/tau-dev-claims.json")
SWEEP = Path("reports/tau-sweep.json")
FIGURE = Path("assets/tau-curve.svg")
TAUS = [round(0.05 * i, 2) for i in range(1, 20)]


async def collect(as_of: date, config_paths: list[str]) -> None:
    verifier = get_verifier()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    dev = [r for r in rows if r.get("split") == "dev"]
    out = []
    for path in config_paths:
        config = RunConfig.from_yaml(path)
        config.guard.enabled = False
        out += await _collect(config, dev, verifier, as_of)
    CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    CLAIMS.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {CLAIMS}: label every claim's `grounded`, then run `sweep`")


async def _collect(config: RunConfig, dev: list[dict], verifier, as_of: date) -> list[dict]:
    out = []
    for r in dev:
        answer = await answer_question(r["question"], config, as_of=as_of)
        by_label = {s.label: s for s in answer.sources}
        claims = []
        if answer.status in ("answered", "partial"):
            for claim in split_claims(answer.answer):
                cited = [by_label[c].chunk.text for c in claim.citations if c in by_label]
                premise = "\n".join(cited)
                others = {
                    label: verifier.entailment(s.chunk.text, claim.text)
                    for label, s in by_label.items() if label not in claim.citations
                }
                best_other = max(others, key=others.get) if others else None
                claims.append({
                    "text": claim.text,
                    "citations": claim.citations,
                    "cited_score": round(verifier.entailment(premise, claim.text), 4)
                    if premise else 0.0,
                    "other_label": best_other,
                    "other_score": round(others[best_other], 4) if best_other else 0.0,
                    "premise": premise,
                    "other_premise": by_label[best_other].chunk.text if best_other else "",
                    "grounded": None,
                })
        print(f"{config.name} {r['id']}: {answer.status} {len(claims)} claims", flush=True)
        out.append({
            "config": config.name, "id": r["id"], "type": r["type"], "question": r["question"],
            "gold_answer": r.get("gold_answer"), "status": answer.status,
            "abstain_reason": answer.meta.abstain_reason, "answer": answer.answer,
            "claims": claims,
        })
    return out


def rescore() -> None:
    """Re-score the labelled claims after a verifier change - no LLM, labels kept.
    Only the best other source's text is stored, so that one is re-scored, not
    re-chosen."""
    verifier = get_verifier()
    cases = json.loads(CLAIMS.read_text(encoding="utf-8"))
    for case in cases:
        for c in case["claims"]:
            c["cited_score"] = round(verifier.entailment(c["premise"], c["text"]), 4) \
                if c["premise"] else 0.0
            c["other_score"] = round(verifier.entailment(c["other_premise"], c["text"]), 4) \
                if c["other_premise"] else 0.0
    CLAIMS.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {CLAIMS} re-scored")


def passes(claim: dict, tau: float) -> bool:
    """The guard's verdict at τ: the cited sources, or failing those the best
    other retrieved source, must entail the claim. Uncited claims never pass."""
    if not claim["citations"]:
        return False
    return claim["cited_score"] >= tau or claim["other_score"] >= tau


def sweep() -> None:
    cases = json.loads(CLAIMS.read_text(encoding="utf-8"))
    claims = [c for case in cases for c in case["claims"]]
    unlabelled = [c["text"][:60] for c in claims if c["grounded"] is None]
    if unlabelled:
        raise SystemExit(f"{len(unlabelled)} claims have no `grounded` label, e.g. {unlabelled[0]}")
    grounded = [c for c in claims if c["grounded"]]
    ungrounded = [c for c in claims if not c["grounded"]]
    # answerable questions the model did answer: would the guard leave anything?
    answered = [case for case in cases if case["type"] == "answerable" and case["claims"]]

    curve = []
    for tau in TAUS:
        blocked_bad = sum(not passes(c, tau) for c in ungrounded)
        blocked_good = sum(not passes(c, tau) for c in grounded)
        blocked = blocked_bad + blocked_good
        emptied = sum(
            not any(passes(c, tau) for c in case["claims"] if c["grounded"]) for case in answered
        )
        curve.append({
            "tau": tau,
            "catch_rate": round(blocked_bad / len(ungrounded), 4) if ungrounded else None,
            "block_precision": round(blocked_bad / blocked, 4) if blocked else None,
            "false_block_rate": round(blocked_good / len(grounded), 4) if grounded else None,
            "answers_emptied": round(emptied / len(answered), 4) if answered else None,
        })

    summary = {
        "questions": len(cases), "claims": len(claims),
        "grounded": len(grounded), "ungrounded": len(ungrounded),
        "answerable_answered": len(answered),
    }
    SWEEP.write_text(json.dumps({"summary": summary, "curve": curve}, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    print(f"{'τ':>5} {'catch':>6} {'prec':>6} {'false blk':>9} {'emptied':>7}")
    for p in curve:
        print(f"{p['tau']:5.2f} {_f(p['catch_rate'])} {_f(p['block_precision'])} "
              f"{_f(p['false_block_rate']):>9} {_f(p['answers_emptied']):>7}")
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    FIGURE.write_text(svg(curve, summary), encoding="utf-8")
    print(f"-> {SWEEP}, {FIGURE}")


def _f(v: float | None) -> str:
    return "  n/a" if v is None else f"{v:6.2f}"


def svg(curve: list[dict], summary: dict, chosen: float = 0.50) -> str:
    """Two rates against τ, one axis, direct labels, light and dark."""
    w, h, left, right, top, bottom = 640, 360, 56, 150, 48, 48
    pw, ph = w - left - right, h - top - bottom
    x = lambda t: left + t * pw  # noqa: E731
    y = lambda v: top + (1 - v) * ph  # noqa: E731
    series = [
        ("catch_rate", "series-1", "câu không căn cứ bị chặn"),
        ("false_block_rate", "series-2", "câu đúng bị chặn nhầm"),
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'font-family="system-ui, sans-serif" font-size="12" role="img" '
        f'aria-label="Tỉ lệ chặn của guard theo ngưỡng tau">',
        "<style>"
        ".bg{fill:#fcfcfb}.ink{fill:#0b0b0b}.muted{fill:#52514e}.grid{stroke:#e4e3de}"
        ".line{fill:none}.series-1{stroke:#2a78d6}.series-2{stroke:#eb6834}"
        ".dot.series-1{fill:#2a78d6}.dot.series-2{fill:#eb6834}.pick{stroke:#52514e}"
        "@media (prefers-color-scheme: dark){.bg{fill:#1a1a19}.ink{fill:#fff}"
        ".muted{fill:#c3c2b7}.grid{stroke:#383835}"
        ".series-1{stroke:#3987e5}.series-2{stroke:#d95926}"
        ".dot.series-1{fill:#3987e5}.dot.series-2{fill:#d95926}.pick{stroke:#c3c2b7}}"
        "</style>",
        f'<rect class="bg" width="{w}" height="{h}" rx="8"/>',
        f'<text class="ink" x="{left}" y="24" font-size="14" font-weight="600">'
        f"Guard trên tập dev theo τ</text>",
        f'<text class="muted" x="{left}" y="40">{summary["claims"]} mệnh đề gán nhãn tay '
        f'({summary["ungrounded"]} không căn cứ), 20 câu dev, cấu hình full và baseline</text>',
    ]
    for v in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y(v)}" y2="{y(v)}"/>')
        parts.append(f'<text class="muted" x="{left - 8}" y="{y(v) + 4}" '
                     f'text-anchor="end">{int(v * 100)}%</text>')
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1):
        parts.append(f'<text class="muted" x="{x(t)}" y="{top + ph + 18}" '
                     f'text-anchor="middle">{t:.1f}</text>')
    parts.append(f'<text class="muted" x="{left + pw / 2}" y="{h - 8}" '
                 f'text-anchor="middle">ngưỡng τ</text>')
    parts.append(f'<line class="pick" stroke-dasharray="4 4" x1="{x(chosen)}" x2="{x(chosen)}" '
                 f'y1="{top}" y2="{top + ph}"/>')
    parts.append(f'<text class="muted" x="{x(chosen) + 6}" y="{top + 12}">τ = {chosen:.2f}</text>')
    for key, cls, label in series:
        pts = [(p["tau"], p[key]) for p in curve if p[key] is not None]
        if not pts:
            continue
        path = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
        parts.append(f'<polyline class="line {cls}" stroke-width="2" points="{path}"/>')
        for t, v in pts:
            parts.append(f'<circle class="dot {cls}" cx="{x(t):.1f}" cy="{y(v):.1f}" r="4">'
                         f"<title>τ={t:.2f}: {v:.0%} {label}</title></circle>")
        t, v = pts[-1]
        parts.append(f'<text class="ink" x="{x(t) + 10:.1f}" y="{y(v) + 4:.1f}">{label}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["collect", "rescore", "sweep"])
    ap.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 15))
    ap.add_argument("--config", action="append",
                    default=None, help="repeatable; default: full and baseline")
    args = ap.parse_args()
    if args.step == "collect":
        asyncio.run(collect(args.as_of, args.config or ["configs/full.yaml",
                                                         "configs/baseline.yaml"]))
    elif args.step == "rescore":
        rescore()
    else:
        sweep()


if __name__ == "__main__":
    main()
