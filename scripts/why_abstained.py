"""Which layer refuses the questions that do have an answer?

`correct_abstention_by_layer` in a report counts the unanswerable questions each
layer caught - the layers doing their job. This is the mirror image: for every
question the corpus *does* answer, which layer stopped it anyway.

    python scripts/why_abstained.py reports/full.json

A false abstention is not one failure mode. The retrieval floor missing a clause
and the guard rejecting a correct sentence need opposite fixes, and the headline
`false_abstention` number hides which one you have.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

LAYER = {
    "retrieval_floor": "ngưỡng truy xuất - không đoạn nào đủ điểm",
    "out_of_domain": "planner - cho là không phải câu hỏi pháp luật",
    "model": "model tự từ chối - đã thấy tài liệu, vẫn không trả lời",
    "guard": "guard NLI - loại hết mệnh đề, hoặc sinh ra 0 mệnh đề",
    None: "không ghi lý do",
}


def main(paths: list[str]) -> int:
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        cases = report["cases"]
        answerable = [c for c in cases if c["type"] == "answerable"]
        refused = [c for c in answerable if c["status"] in ("abstained", "no_context")]

        print(f"\n=== {report['config']}  ({path})")
        print(f"{len(answerable)} câu có đáp án, {len(refused)} bị từ chối "
              f"= {len(refused) / max(len(answerable), 1):.0%} false abstention")
        if errored := report.get("errored"):
            print(f"[!] {len(errored)} câu lỗi provider, không nằm trong mẫu số")

        by_reason = Counter(c["abstain_reason"] for c in refused)
        for reason, n in by_reason.most_common():
            share = n / max(len(refused), 1)
            print(f"  {n:3}  {share:>5.0%}  {LAYER.get(reason, reason)}")

        # A guard refusal with sources retrieved but no claims is the "[C1]"
        # shape: a generation that produced nothing citable.
        empty = [c for c in refused
                 if c["abstain_reason"] == "guard" and c["sources"] and not c["guard_claims"]]
        if empty:
            print(f"\n  {len(empty)} trong số đó: có nguồn, 0 mệnh đề "
                  f"-> lượt sinh hỏng, không phải guard chặn")
            for c in empty[:5]:
                print(f"      {c['id']}  {c['question'][:58]}")

        # Retrieved the gold clause and still refused: the guard is the problem.
        blocked = [c for c in refused
                   if c["abstain_reason"] == "guard" and c["guard_claims"]]
        if blocked:
            print(f"\n  {len(blocked)} trong số đó: guard loại hết mệnh đề")
            for c in blocked[:5]:
                worst = min((cl.get("entailment") or 0.0) for cl in c["guard_claims"])
                print(f"      {c['id']}  ent thấp nhất={worst:.2f}  {c['question'][:48]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["reports/full.json"]))
