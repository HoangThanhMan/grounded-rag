"""Label agreement on the evaluation set: a blind relabel of 60 questions.

    python scripts/agreement.py sample --annotator intra   # -> eval/dataset/agreement/
    # fill in "type" (and "gold_articles" when answerable) for every row,
    # without opening questions.jsonl
    python scripts/agreement.py score

A label is only as good as its agreement with a second reading. 20% of the set
(60 questions, stratified by type) is labelled again from the question alone:
by a second person (`inter`), or by the first labeller after at least
MIN_DAYS days (`intra`) - long enough to have forgotten the answers. `score`
reports Cohen's κ on the four-way type and on answerable / unanswerable, and,
where both readings say answerable, how often they cite the same article.
LABELING.md wants κ ≥ 0.7, and says which kind of agreement was measured.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")

from eval.stats import cohen_kappa  # noqa: E402

DATASET = Path("eval/dataset/questions.jsonl")
SHEET = Path("eval/dataset/agreement/relabel.json")
SUMMARY = SHEET.with_name("relabel.summary.json")
N = 60
SEED = 26
MIN_DAYS = 10
TYPES = ("answerable", "unanswerable_out_of_scope", "unanswerable_false_premise",
         "unanswerable_near_miss")


def draw(rows: list[dict], n: int = N, seed: int = SEED) -> list[dict]:
    """n questions, each type in proportion to the set."""
    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = {t: [r for r in rows if r["type"] == t] for t in TYPES}
    picked = []
    for group in by_type.values():
        k = round(n * len(group) / len(rows))
        picked += rng.sample(group, k)
    return sorted(picked, key=lambda r: r["id"])


def sample(annotator: str) -> None:
    if SHEET.exists():
        raise SystemExit(f"{SHEET} exists; a relabel is drawn once")
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    sheet = {"annotator": annotator, "drawn_on": date.today().isoformat(),
             "rows": [{"id": r["id"], "question": r["question"], "as_of": r.get("as_of"),
                       "type": None, "gold_articles": []} for r in draw(rows)]}
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    SHEET.write_text(json.dumps(sheet, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(sheet['rows'])} questions -> {SHEET} ({annotator})")


def article(ref: str) -> str:
    return ":".join(ref.split(":")[:2])


def score(today: date | None = None) -> dict:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    today = today or date.today()
    waited = (today - date.fromisoformat(sheet["drawn_on"])).days
    if sheet["annotator"] == "intra" and waited < MIN_DAYS:
        raise SystemExit(f"intra-annotator relabel drawn {waited} days ago; wait {MIN_DAYS}")
    gold = {json.loads(line)["id"]: json.loads(line)
            for line in DATASET.read_text(encoding="utf-8").splitlines() if line}
    rows = sheet["rows"]
    missing = [r["id"] for r in rows if r["type"] not in TYPES]
    if missing:
        raise SystemExit(f"unlabelled: {missing}")
    first = [gold[r["id"]]["type"] for r in rows]
    second = [r["type"] for r in rows]
    both = [(gold[r["id"]], r) for r in rows
            if gold[r["id"]]["answerable"] and r["type"] == "answerable"]
    same_article = [bool({article(g) for g in q["gold_chunks"]} & set(r["gold_articles"]))
                    for q, r in both]
    summary = {
        "annotator": sheet["annotator"], "n": len(rows), "days_between": waited,
        "kappa_type": cohen_kappa(first, second),
        "kappa_answerable": cohen_kappa(
            ["answerable" if t == "answerable" else "unanswerable" for t in first],
            ["answerable" if t == "answerable" else "unanswerable" for t in second]),
        "same_gold_article": round(sum(same_article) / len(same_article), 4) if both else None,
        "disagreements": [{"id": r["id"], "first": f, "second": r["type"]}
                          for r, f in zip(rows, first, strict=True) if f != r["type"]],
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "disagreements"}, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "score"])
    ap.add_argument("--annotator", choices=["intra", "inter"], default="intra")
    args = ap.parse_args()
    if args.step == "sample":
        sample(args.annotator)
    else:
        score()


if __name__ == "__main__":
    main()
