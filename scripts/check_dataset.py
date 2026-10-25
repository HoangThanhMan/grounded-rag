"""Check eval/dataset/questions.jsonl against the corpus.

Run before trusting any number produced from the dataset:

    python scripts/check_dataset.py

Every gold ref is resolved through the same ClauseIndex the evaluation scores
with, so a ref that passes here is a ref the metrics can find. Every number in
a gold answer has to appear in the clause it cites - that catches the
transcription slips hand labelling actually makes. Unanswerable questions are
searched for full text, because the expensive mistake is a question labelled
unanswerable that the corpus quietly answers (LABELING.md, step 5).

The v2 split rules are checked too: questions that share a gold article share an
`article_group` and a split, so τ is never calibrated on the article a test
question is scored on; the v1 dev questions are still in dev; every temporal
pair asks one question on two dates, gets two different answers, and each gold
document is in force on the date it is asked for.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from eval.instrument import ClauseIndex  # noqa: E402
from grounded_rag.ingest.loaders import iter_corpus, load_file  # noqa: E402

DATASET = Path("eval/dataset/questions.jsonl")
CORPUS = Path("data/corpus")

# LABELING.md - v2: 300 questions, dev 60 / test 240
EXPECTED = {
    "answerable": 180,
    "unanswerable_out_of_scope": 40,
    "unanswerable_false_premise": 40,
    "unanswerable_near_miss": 40,
}
EXPECTED_DEV = {
    "answerable": 42,
    "unanswerable_out_of_scope": 6,
    "unanswerable_false_premise": 6,
    "unanswerable_near_miss": 6,
}
# the v1 dev split: τ was calibrated on these, so they may never reach test
V1_DEV = {"a005", "a010", "a015", "a020", "a025", "a030", "a035", "a040", "a045", "a050",
          "a055", "a060", "a063", "u005", "u010", "u015", "u020", "u025", "u030", "u035"}
MIN_TEMPORAL = 20
TAGS = {"colloquial", "multi_part", "temporal"}
SOURCES = {"chunk_generated", "handwritten", "tvpl", "zalo"}

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
    validity = {d.doc_id: d.meta for d in map(load_file, iter_corpus(CORPUS))}
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    errors: list[str] = []
    warnings: list[str] = []
    check_split(rows, errors)
    check_temporal(rows, validity, errors)
    for r in rows:
        if r.get("source") not in SOURCES:
            errors.append(f"{r['id']}: source {r.get('source')!r} not in {sorted(SOURCES)}")
        if r.get("source") == "tvpl" and not r.get("source_id"):
            errors.append(f"{r['id']}: TVPL question without source_id (CC-BY-SA attribution)")
        if unknown := set(r.get("tags", [])) - TAGS:
            errors.append(f"{r['id']}: unknown tags {sorted(unknown)}")

    counts = Counter(r["type"] for r in rows)
    for typ, want in EXPECTED.items():
        if counts[typ] != want:
            errors.append(f"{typ}: {counts[typ]} questions, LABELING.md says {want}")

    seen: set[tuple[str, str | None]] = set()
    for r in rows:
        qid = r["id"]
        # a temporal pair asks the same question on two dates
        key = (r["question"], r.get("as_of"))
        if key in seen:
            errors.append(f"{qid}: duplicate question")
        seen.add(key)

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


def article(ref: str) -> str:
    return ":".join(ref.split(":")[:2])


def check_split(rows: list[dict], errors: list[str]) -> None:
    """Whole article groups per split, groups consistent with the gold, v1 dev kept."""
    group_split: dict[str, set[str]] = defaultdict(set)
    article_group: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if not r.get("article_group") or r.get("split") not in ("dev", "test"):
            errors.append(f"{r['id']}: missing article_group or split")
            continue
        group_split[r["article_group"]].add(r["split"])
        for ref in r["gold_chunks"]:
            article_group[article(ref)].add(r["article_group"])
    errors += [f"group {g} is in both splits" for g, s in group_split.items() if len(s) > 1]
    errors += [f"article {a} spans groups {sorted(g)}" for a, g in article_group.items()
               if len(g) > 1]
    moved = sorted(r["id"] for r in rows if r["id"] in V1_DEV and r.get("split") != "dev")
    if moved:
        errors.append(f"v1 dev questions moved out of dev (τ was calibrated on them): {moved}")
    dev = Counter(r["type"] for r in rows if r.get("split") == "dev")
    if dev != Counter(EXPECTED_DEV):
        errors.append(f"dev split {dict(dev)}, LABELING.md says {EXPECTED_DEV}")


def check_temporal(rows: list[dict], validity: dict, errors: list[str]) -> None:
    """Each pair: one question, two dates, two answers, gold in force on each date."""
    pairs: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        temporal = "temporal" in r.get("tags", [])
        if temporal != bool(r.get("temporal_pair")) or temporal != bool(r.get("as_of")):
            errors.append(f"{r['id']}: temporal tag, temporal_pair and as_of must go together")
            continue
        if not temporal:
            continue
        pairs[r["temporal_pair"]].append(r)
        on = date.fromisoformat(r["as_of"])
        for ref in r["gold_chunks"]:
            meta = validity.get(ref.split(":")[0])
            if meta is None:
                continue
            if (meta.effective_date and meta.effective_date > on) or (
                    meta.expiry_date and meta.expiry_date <= on):
                errors.append(f"{r['id']}: {ref} is not in force on {on}")
    if sum(len(p) for p in pairs.values()) < MIN_TEMPORAL:
        errors.append(f"fewer than {MIN_TEMPORAL} temporal questions")
    for name, members in pairs.items():
        if (len(members) != 2 or len({m["question"] for m in members}) != 1
                or len({m["as_of"] for m in members}) != 2
                or len({m["gold_answer"] for m in members}) != 2):
            errors.append(f"temporal pair {name}: needs one question, two dates, two answers")


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
