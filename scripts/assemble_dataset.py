"""Assemble eval/dataset/questions.jsonl v2 from the reviewed drafts.

    python scripts/assemble_dataset.py

Inputs, all in eval/dataset/drafts/ (LABELING.md, "v2"):
  tvpl.jsonl                      reviewed TVPL-Retrieval-VN candidates (keep / skip)
  temporal_and_handwritten.jsonl  temporal pairs and handwritten answerable questions
  unanswerable.jsonl              handwritten unanswerable questions

The 100 v1 questions keep their ids, labels and gold. New questions get the
next free ids. Then two things are computed, never hand-edited:

  article_group  questions that share a gold article are one group (union-find
                 over articles), and both halves of a temporal pair are one
                 group. An unanswerable question is its own group.
  split          dev 60 / test 240, whole groups only, so τ is never calibrated
                 on the article a test question is scored on. The v1 dev
                 questions stay in dev - τ was fitted on them. Within that, the
                 split is drawn with a fixed seed to match each type's count and
                 keep the tag mix of dev close to the whole set.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

DATASET = Path("eval/dataset/questions.jsonl")
DRAFTS = Path("eval/dataset/drafts")
SEED = 20261026
TRIES = 3000
# 60 dev questions. Proportional would be 36 answerable + 8 of each unanswerable
# type, but the v1 dev questions must stay in dev and their article groups
# already hold 42 answerable questions; the test split keeps its 240.
DEV = {"answerable": 42, "unanswerable_out_of_scope": 6,
       "unanswerable_false_premise": 6, "unanswerable_near_miss": 6}
TAGS = ("colloquial", "multi_part", "temporal")


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def article(ref: str) -> str:
    """doc:Điều N:k -> doc:Điều N"""
    return ":".join(ref.split(":")[:2])


def next_ids(rows: list[dict], prefix: str):
    n = max(int(r["id"][1:]) for r in rows if r["id"].startswith(prefix))
    while True:
        n += 1
        yield f"{prefix}{n:03d}"


def build() -> list[dict]:
    rows = read(DATASET)
    assert len(rows) == 100 and all("article_group" not in r for r in rows), "already assembled"
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["source"] = "chunk_generated" if r["answerable"] else "handwritten"
    a_ids, u_ids = next_ids(rows, "a"), next_ids(rows + [{"id": "u040"}], "u")

    for d in read(DRAFTS / "tvpl.jsonl"):
        if d["decision"] != "keep":
            continue
        rows.append({"id": next(a_ids), "question": d["question"], "answerable": True,
                     "gold_answer": d["gold_answer"], "gold_chunks": d["gold_chunks"],
                     "type": "answerable", "tags": d["tags"], "source": "tvpl",
                     "source_id": d["source_id"]})

    for d in read(DRAFTS / "temporal_and_handwritten.jsonl"):
        if d["reuse"]:
            old = by_id[d["reuse"]]
            assert old["question"] == d["question"], d["reuse"]
            old["as_of"] = d["as_of"]
            old["tags"] = sorted(set(old.get("tags", [])) | set(d["tags"]))
            old["temporal_pair"] = d["pair"]
            continue
        row = {"id": next(a_ids), "question": d["question"], "answerable": True,
               "gold_answer": d["gold_answer"], "gold_chunks": d["gold_chunks"],
               "type": "answerable", "tags": d["tags"], "source": "handwritten"}
        if d["as_of"]:
            row["as_of"] = d["as_of"]
            row["temporal_pair"] = d["pair"]
        rows.append(row)

    for d in read(DRAFTS / "unanswerable.jsonl"):
        rows.append({"id": next(u_ids), "question": d["question"], "answerable": False,
                     "gold_answer": None, "gold_chunks": [], "type": d["type"], "tags": [],
                     "source": d["source"]})

    for r in rows:
        r.setdefault("tags", [])
        # multi_part means the gold spans several clauses (check_dataset.py)
        if "multi_part" in r["tags"] and len(r["gold_chunks"]) < 2:
            r["tags"].remove("multi_part")
    return rows


def assign_groups(rows: list[dict]) -> None:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for r in rows:
        keys = [f"q:{r['id']}"] + [f"art:{article(g)}" for g in r["gold_chunks"]]
        if r.get("temporal_pair"):
            keys.append(f"pair:{r['temporal_pair']}")
        for k in keys[1:]:
            union(keys[0], k)
    members: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        members[find(f"q:{r['id']}")].append(r)
    for group in members.values():
        arts = sorted({article(g) for r in group for g in r["gold_chunks"]})
        name = arts[0] if arts else group[0]["id"]
        if len(arts) > 1:
            name += f" +{len(arts) - 1}"
        for r in group:
            r["article_group"] = name


def assign_split(rows: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["article_group"]].append(r)
    forced = {r["article_group"] for r in rows if r.get("split") == "dev"}
    overall = Counter(t for r in rows for t in r["tags"])
    rng = random.Random(SEED)
    best, best_cost = None, float("inf")
    names = sorted(groups)
    for _ in range(TRIES):
        rng.shuffle(names)
        dev, counts = set(forced), Counter(r["type"] for g in forced for r in groups[g])
        if any(counts[t] > DEV[t] for t in DEV):
            raise SystemExit(f"v1 dev groups alone exceed the dev quota: {dict(counts)}")
        for g in names:
            if g in dev:
                continue
            c = Counter(r["type"] for r in groups[g])
            if all(counts[t] + c[t] <= DEV[t] for t in c):
                dev.add(g)
                counts += c
        if counts != Counter(DEV):
            continue
        dev_rows = [r for g in dev for r in groups[g]]
        tags = Counter(t for r in dev_rows for t in r["tags"])
        cost = sum(abs(tags[t] / len(dev_rows) - overall[t] / len(rows)) for t in TAGS)
        if cost < best_cost:
            best, best_cost = set(dev), cost
    if best is None:
        raise SystemExit("no split matches the dev quota; loosen DEV or check group sizes")
    for r in rows:
        r["split"] = "dev" if r["article_group"] in best else "test"


FIELDS = ["id", "question", "answerable", "gold_answer", "gold_chunks", "type", "tags", "as_of",
          "temporal_pair", "article_group", "split", "source", "source_id", "relabelled_from"]


def main() -> int:
    rows = build()
    assign_groups(rows)
    assign_split(rows)
    rows.sort(key=lambda r: (r["id"][0], int(r["id"][1:])))
    out = []
    for r in rows:
        assert set(r) <= set(FIELDS), set(r) - set(FIELDS)
        out.append({k: r[k] for k in FIELDS if k in r})
    DATASET.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), "utf-8")
    split = Counter((r["split"], r["type"]) for r in out)
    sizes = Counter(Counter(r["article_group"] for r in out).values())
    print(f"{len(out)} questions -> {DATASET}")
    print("  split:", dict(sorted(split.items())))
    print("  group sizes:", dict(sorted(sizes.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
