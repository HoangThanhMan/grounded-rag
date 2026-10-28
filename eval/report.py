"""The results table, from eval/results/<system>.jsonl:

    python -m eval.report > eval/results/summary.md
"""

from __future__ import annotations

import json

from eval.run import RESULTS

LABELS = {
    "naive": "Naive RAG: fixed-size chunks, dense search, no floor",
    "app": "This app: clause chunks, hybrid search + rerank, floor",
}
COLUMNS = {
    "hit_at_5": "Gold clause retrieved (top 5) ↑",
    "correct": "Correct answer ↑",
    "correct_refusal": "Refuses when the law is silent ↑",
    "false_refusal": "Refuses an answerable question ↓",
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


def main() -> None:
    results = {}
    for system in LABELS:
        path = RESULTS / f"{system}.jsonl"
        if path.exists():
            results[system] = [json.loads(line) for line in path.read_text().splitlines() if line]
    print(table(results))
    sizes = {s: len(rows) for s, rows in results.items()}
    if any(n < 100 for n in sizes.values()):
        print(f"\nIncomplete run: {sizes} of 100 questions answered.")


if __name__ == "__main__":
    main()
