"""Check eval/dataset/questions.jsonl against the corpus.

Run before trusting any number produced from the dataset:

    python scripts/check_dataset.py

Every gold ref is resolved through the same ClauseIndex the evaluation scores
with, so a ref that passes here is a ref the metrics can find. Every number in
a gold answer has to appear in the clause it cites - that catches the
transcription slips hand labelling actually makes. Unanswerable questions are
searched for full text, because the expensive mistake is a question labelled
unanswerable that the corpus quietly answers (LABELING.md, step 5).
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from eval.instrument import ClauseIndex  # noqa: E402

DATASET = Path("eval/dataset/questions.jsonl")
CORPUS = Path("data/corpus")

# LABELING.md - the split the README reports
EXPECTED = {
    "answerable": 63,
    "unanswerable_out_of_scope": 15,
    "unanswerable_false_premise": 13,
    "unanswerable_near_miss": 9,
}

NUM = re.compile(r"\d+(?:[.,]\d+)?")
# Vietnamese legal drafting writes "08 giờ" where a question says "8 giờ"
norm_num = lambda s: s.lstrip("0") or "0"  # noqa: E731


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s.lower())
    return re.findall(r"\w+", s)


def main() -> int:
    if not CORPUS.exists():
        print(f"no corpus at {CORPUS} - run `make corpus` first")
        return 2

    gold_text = ClauseIndex(CORPUS).gold_text()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    errors: list[str] = []
    warnings: list[str] = []

    counts = Counter(r["type"] for r in rows)
    for typ, want in EXPECTED.items():
        if counts[typ] != want:
            errors.append(f"{typ}: {counts[typ]} questions, LABELING.md says {want}")

    seen: set[str] = set()
    for r in rows:
        qid = r["id"]
        if r["question"] in seen:
            errors.append(f"{qid}: duplicate question")
        seen.add(r["question"])

        if not r["answerable"]:
            if r["gold_chunks"] or r["gold_answer"]:
                errors.append(f"{qid}: unanswerable but carries gold")
            # A question is only unanswerable if the corpus really is silent.
            hits = [ref for ref, text in gold_text.items() if covered(r["question"], text)]
            if hits:
                warnings.append(
                    f"{qid}: corpus may answer this - {hits[:3]} - {r['question'][:60]}"
                )
            continue

        if not r["gold_chunks"]:
            errors.append(f"{qid}: answerable with no gold_chunks")
        for ref in r["gold_chunks"]:
            if ref not in gold_text:
                errors.append(f"{qid}: gold ref not in corpus - {ref}")
                continue
            missing = [
                n for n in NUM.findall(r["gold_answer"] or "")
                if not any(norm_num(n) == norm_num(m) for m in NUM.findall(gold_text[ref]))
            ]
            if missing and len(r["gold_chunks"]) == 1:
                warnings.append(f"{qid}: numbers {missing} not in {ref}")

    tags = Counter(t for r in rows for t in r.get("tags", []))
    for tag in ("multi_part", "colloquial"):
        if tags[tag] < 8:
            warnings.append(f"only {tags[tag]} questions tagged {tag}; LABELING.md wants about 10")
    bad_multi = [r["id"] for r in rows
                 if "multi_part" in r.get("tags", []) and len(r["gold_chunks"]) < 2]
    if bad_multi:
        errors.append(f"multi_part with a single gold clause: {bad_multi}")

    print(f"{len(rows)} questions, {dict(counts)}, tags {dict(tags)}")
    print(f"{len(gold_text)} clauses indexed from {CORPUS}")
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print("ok" if not errors else f"{len(errors)} errors")
    return 1 if errors else 0


def covered(question: str, clause: str) -> bool:
    """Crude: every content word of the question appears in this one clause.
    Over-flags rather than under-flags - a warning is a prompt to read, not a
    verdict."""
    stop = {"bao", "nhiêu", "là", "được", "có", "không", "của", "cho", "và",
            "thì", "mấy", "gì", "nào", "phải", "trong", "một", "khi", "người"}
    w = {x for x in words(question) if x not in stop and len(x) > 2}
    return len(w) >= 4 and w <= set(words(clause))


if __name__ == "__main__":
    raise SystemExit(main())
