"""The results tables, from eval/results/<system>.jsonl and <system>_hard.jsonl:

    python -m eval.report > eval/results/summary.md
"""

from __future__ import annotations

import json

from eval.run import RESULTS

LABELS = {
    "naive": "Naive RAG: fixed-size chunks, dense search, no floor",
    "app_v1": "This app before chunk context (index v1)",
    "app": "This app: clause chunks, hybrid search + rerank, floor",
    "app_cascade": "This app + a stronger model when the first answer fails the checks",
}
COLUMNS = {
    "hit_at_5": "Gold clause retrieved (top 5) ↑",
    "correct": "Correct answer ↑",
    "correct_refusal": "Refuses when the law is silent ↑",
    "false_refusal": "Refuses an answerable question ↓",
}


HARD_COLUMNS = {
    "hit_at_5": "A gold clause retrieved ↑",
    "all_gold_retrieved": "Every gold clause retrieved ↑",
    "correct": "Correct answer ↑",
    "complete": "Complete: cites every gold clause ↑",
    "cites_wrong_scheme": "Cites the wrong scheme ↓",
    "false_refusal": "Refuses ↓",
}


def rate(rows: list[dict], column: str) -> str:
    values = [r[column] for r in rows if r.get(column) is not None]
    if not values:
        return "–"
    hits = sum(bool(v) for v in values)
    return f"{hits / len(values):.2f} ({hits}/{len(values)})"


def table(results: dict[str, list[dict]]) -> str:
    lines = [
        "| System | " + " | ".join(COLUMNS.values()) + " |",
        "|---|" + "---|" * len(COLUMNS),
    ]
    for system, rows in results.items():
        cells = " | ".join(rate(rows, c) for c in COLUMNS)
        lines.append(f"| {LABELS.get(system, system)} | {cells} |")
    return "\n".join(lines)


def escalations(results: dict[str, list[dict]]) -> list[str]:
    """For each run that asked a stronger model at all: how often, and which."""
    lines = []
    for system, rows in results.items():
        redone = [r for r in rows if r.get("escalated")]
        if redone:
            models = ", ".join(sorted({r["model"] for r in redone}))
            lines.append(f"{system}: {len(redone)}/{len(rows)} answers redone by {models}")
    return lines


def hard_table(results: dict[str, list[dict]]) -> str:
    """One row per system and kind of hard question: each kind fails differently."""
    lines = [
        "| System | Kind (n) | " + " | ".join(HARD_COLUMNS.values()) + " |",
        "|---|---|" + "---|" * len(HARD_COLUMNS),
    ]
    for system, rows in results.items():
        for kind in sorted({r["type"] for r in rows}):
            group = [r for r in rows if r["type"] == kind]
            cells = " | ".join(rate(group, c) for c in HARD_COLUMNS)
            lines.append(f"| {system} | {kind} ({len(group)}) | {cells} |")
    return "\n".join(lines)


def _load(suffix: str = "") -> dict[str, list[dict]]:
    results = {}
    for system in LABELS:
        path = RESULTS / f"{system}{suffix}.jsonl"
        if path.exists():
            results[system] = [json.loads(line) for line in path.read_text().splitlines() if line]
    return results


def main() -> None:
    results = _load()
    print(table(results))
    sizes = {s: len(rows) for s, rows in results.items()}
    if any(n < 100 for n in sizes.values()):
        print(f"\nIncomplete run: {sizes} of 100 questions answered.")
    for line in escalations(results):
        print(f"\n{line}")
    if hard := _load("_hard"):
        print("\n### Hard questions\n")
        print(hard_table(hard))
        for line in escalations(hard):
            print(f"\n{line}")


if __name__ == "__main__":
    main()
