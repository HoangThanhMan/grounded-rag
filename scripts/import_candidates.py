"""Candidate questions from a public legal Q&A set, with gold refs proposed.

    python scripts/import_candidates.py <TVPL-Retrieval-VN folder>
    # -> eval/dataset/candidates/tvpl.jsonl

TVPL-Retrieval-VN (GreenNode on Hugging Face, CC-BY-SA-4.0) pairs questions
people actually asked with the passages that answer them. Its corpus spans many
laws and carries no document numbers, so a question is kept only when one of
its passages is found word for word in this project's corpus: a line of at
least MIN_WORDS words that appears inside one clause. That clause becomes a
proposed gold ref.

These are candidates, not dataset rows. Every one still goes through
LABELING.md: rewrite the question against the corpus, write the gold answer,
confirm or correct the refs. A ref inside Điều 219 of Bộ luật Lao động is
flagged: that article quotes the old Luật BHXH 2014 it amended, so the
question is answered by a law no longer in force - a temporal candidate, not
an answerable one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from eval.instrument import ClauseIndex  # noqa: E402

OUT = Path("eval/dataset/candidates/tvpl.jsonl")
MIN_WORDS = 15
# lines every law shares; matching one says nothing about the topic
BOILERPLATE = re.compile(
    r"từ ngữ dưới đây được hiểu|có hiệu lực thi hành|quy định chi tiết|phạm vi điều chỉnh"
    r"|đối tượng áp dụng|hướng dẫn thi hành",
    re.I,
)
AMENDING_ARTICLE = "bo_luat_lao_dong_2019:Điều 219"


def words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def clause_refs(passage: str, clauses: list[tuple[str, str]]) -> Counter:
    """Clauses that contain a long line of the passage, counted by line."""
    refs: Counter = Counter()
    for line in passage.split("\n"):
        if BOILERPLATE.search(line):
            continue
        w = words(line)
        if len(w) < MIN_WORDS:
            continue
        probe = f" {' '.join(w)} "
        for ref, body in clauses:
            if probe in body:
                refs[ref] += 1
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tvpl", type=Path, help="folder holding the dataset's parquet files")
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("needs pyarrow: pip install -e '.[eval]'") from None

    def rows(sub: str) -> list[dict]:
        return pq.read_table(next((args.tvpl / sub).glob("*.parquet"))).to_pylist()

    questions = {r["_id"]: r["text"] for r in rows("queries")}
    passages = {r["_id"]: r["text"] for r in rows("corpus")}
    qrels: dict[str, list[str]] = defaultdict(list)
    for r in rows("qrels"):
        qrels[r["query-id"]].append(r["corpus-id"])

    clauses = [(c.ref, f" {' '.join(words(c.text))} ") for c in ClauseIndex(args.corpus).clauses]
    by_passage = {pid: clause_refs(text, clauses) for pid, text in passages.items()}

    out = []
    for qid, pids in qrels.items():
        refs: Counter = Counter()
        for pid in pids:
            refs.update(by_passage.get(pid, Counter()))
        if not refs or qid not in questions:
            continue
        ranked = [ref for ref, _ in refs.most_common()]
        out.append({
            "source": "tvpl", "source_id": qid, "question": questions[qid],
            "proposed_gold_chunks": ranked,
            "via_amended_law": any(r.startswith(AMENDING_ARTICLE) for r in ranked),
        })
    out.sort(key=lambda r: r["proposed_gold_chunks"][0])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), "utf-8")
    docs = Counter(r["proposed_gold_chunks"][0].split(":")[0] for r in out)
    print(f"{len(out)} candidates -> {args.out}: {dict(docs)}, "
          f"{sum(r['via_amended_law'] for r in out)} via Điều 219 (old Luật BHXH 2014)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
