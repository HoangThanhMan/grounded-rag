"""Turn several report JSONs into the comparison tables the README needs.

    python -m eval.report reports/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COLUMNS = [
    ("hallucination_rate", "Halluc. ↓"),
    ("correct_abstention", "Correct abst. ↑"),
    ("false_abstention", "False abst. ↓"),
    ("citation_precision", "Cite prec. ↑"),
    ("retrieval_recall", "Retr. recall ↑"),
    ("llm_calls_per_q", "LLM calls/q"),
    ("latency_p95_ms", "p95 (ms)"),
]
LAYERS = ["retrieval_floor", "out_of_domain", "model", "guard"]


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:] if not p.endswith(".ragas.json")]
    if not paths:
        raise SystemExit("usage: python -m eval.report reports/*.json")
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    print("| Configuration | " + " | ".join(c[1] for c in COLUMNS) + " |")
    print("|" + "---|" * (len(COLUMNS) + 1))
    for data in reports:
        m = data["metrics"]
        print(f"| {data['config']} | " + " | ".join(str(m.get(k, "-")) for k, _ in COLUMNS) + " |")

    # Which layer of defence caught the unanswerable questions.
    print("\n| Configuration | " + " | ".join(LAYERS) + " |")
    print("|" + "---|" * (len(LAYERS) + 1))
    for data in reports:
        layers = data["metrics"].get("correct_abstention_by_layer", {})
        print(f"| {data['config']} | " + " | ".join(str(layers.get(k, 0)) for k in LAYERS) + " |")


if __name__ == "__main__":
    main()
