"""Does retrieval actually buy anything, or does the model already know?

The benchmark compares four retrieval configurations against each other. It
never asks the prior question: what does the same model answer with no
documents at all? Without that number, "RAG works" is an assumption.

    python -m eval.closed_book --n 20 --config configs/full.yaml

Scoring is NOT the benchmark's instrument. That one checks a claim against the
passage the answer cited, which a closed-book answer never has. Here both modes
are judged against the same thing: the gold clause for that question.

    entailed   P(entailment | gold clause) >= threshold, per claim
    numbers    every number in the gold answer appears in the answer

`numbers` matters more than it looks in this corpus. Legal answers turn on
"45 ngày", "08 giờ", "85%" - swap the number and the sentence still reads as
fluent, correct Vietnamese. It is also the failure mode the NLI model is
weakest at (docs/08, the day-9 probe).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date
from pathlib import Path

from eval.instrument import ClauseIndex
from eval.run import load_cases
from grounded_rag.config import RunConfig, settings
from grounded_rag.generation.llm_client import LLMUnavailable, get_llm_client
from grounded_rag.guard.claim_splitter import split_claims
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.service import answer_question
from grounded_rag.types import AnswerStatus

# Deliberately not the RAG system prompt: that one demands citations and hands
# the model a refusal sentence, which would force an abstention when there are
# no documents. This asks the model for what it knows, and nothing more.
CLOSED_BOOK_SYSTEM = """Bạn là trợ lý tra cứu pháp luật lao động Việt Nam.
Trả lời ngắn gọn, tối đa 3 câu, đi thẳng vào con số hoặc quy định được hỏi.
Nếu bạn không chắc chắn, hãy nói rõ là không chắc thay vì đoán."""

NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(n: str) -> str:
    """"08 giờ" in the statute, "8 giờ" in an answer: the same number."""
    n = n.replace(",", ".")
    return n.lstrip("0") or "0"


def numbers_covered(gold_answer: str, text: str) -> tuple[int, int]:
    want = {_norm(n) for n in NUM.findall(gold_answer or "")}
    if not want:
        return (0, 0)
    have = {_norm(n) for n in NUM.findall(text or "")}
    return (len(want & have), len(want))


def grounded_in_gold(
    text: str, premises: list[str], verifier, threshold: float
) -> tuple[float, int, int]:
    """Share of the answer's claims the gold clauses actually support."""
    claims = [c for c in split_claims(text) if c.text.strip()]
    if not premises or not claims:
        return (0.0, 0, len(claims))
    ok = 0
    for claim in claims:
        score = max(verifier.entailment(p, claim.text) for p in premises)
        ok += score >= threshold
    return (ok / len(claims), ok, len(claims))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/full.yaml", type=Path)
    ap.add_argument("--dataset", default="eval/dataset/questions.jsonl", type=Path)
    ap.add_argument("--corpus", default="data/corpus", type=Path)
    ap.add_argument("--n", type=int, default=20, help="answerable questions to use")
    ap.add_argument("--threshold", type=float, default=settings.entailment_threshold)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    config = RunConfig.from_yaml(args.config)
    index = ClauseIndex(args.corpus)
    gold_text = index.gold_text()
    verifier = get_verifier()
    llm = get_llm_client()

    cases = [c for c in load_cases(args.dataset) if c["answerable"]][: args.n]
    print(f"{len(cases)} answerable questions | closed book vs {config.name} "
          f"| judge tau={args.threshold}\n")

    rows = []
    for i, case in enumerate(cases, 1):
        gold_a, gold_refs = case.get("gold_answer") or "", case.get("gold_chunks", [])

        try:
            res = await llm.complete(CLOSED_BOOK_SYSTEM, case["question"],
                                     temperature=0.0, max_tokens=300)
            cb_text = res.text.strip()
        except LLMUnavailable as e:
            print(f"[error] {case['id']} closed book: {e}")
            continue

        try:
            rag = await answer_question(case["question"], config, as_of=args.as_of)
        except LLMUnavailable as e:
            print(f"[error] {case['id']} rag: {e}")
            continue
        declined = rag.status in (AnswerStatus.ABSTAINED, AnswerStatus.NO_CONTEXT)
        rag_text = "" if declined else rag.answer

        premises = [gold_text[r] for r in gold_refs if r in gold_text]
        cb_g, cb_ok, cb_n = grounded_in_gold(cb_text, premises, verifier, args.threshold)
        rg_g, rg_ok, rg_n = grounded_in_gold(rag_text, premises, verifier, args.threshold)
        cb_num = numbers_covered(gold_a, cb_text)
        rg_num = numbers_covered(gold_a, rag_text)

        rows.append({
            "id": case["id"], "question": case["question"], "gold_answer": gold_a,
            "gold_chunks": gold_refs,
            "closed_book": {"answer": cb_text, "grounded": round(cb_g, 3),
                            "claims_ok": cb_ok, "claims": cb_n,
                            "numbers": f"{cb_num[0]}/{cb_num[1]}"},
            "rag": {"answer": rag.answer, "status": rag.status, "grounded": round(rg_g, 3),
                    "claims_ok": rg_ok, "claims": rg_n,
                    "numbers": f"{rg_num[0]}/{rg_num[1]}"},
        })
        print(f"[{i}/{len(cases)}] {case['id']}  closed={cb_g:.2f} nums={cb_num[0]}/{cb_num[1]}"
              f"   rag={rg_g:.2f} nums={rg_num[0]}/{rg_num[1]}  ({rag.status})", flush=True)

    if not rows:
        print("nothing scored")
        return 1

    def agg(side: str) -> dict:
        got = [r[side] for r in rows]
        num = [tuple(map(int, r[side]["numbers"].split("/"))) for r in rows]
        hits, want = sum(a for a, _ in num), sum(b for _, b in num)
        answered = [g for g in got if g["claims"]]
        return {
            "grounded_claims": round(sum(g["claims_ok"] for g in got)
                                     / max(sum(g["claims"] for g in got), 1), 4),
            "answers_fully_grounded": round(sum(g["grounded"] == 1.0 for g in answered)
                                            / max(len(answered), 1), 4),
            "gold_numbers_present": round(hits / want, 4) if want else None,
            "answered": len(answered),
        }

    summary = {"n": len(rows), "closed_book": agg("closed_book"), "rag": agg("rag"),
               "config": config.name, "model": settings.llm_model,
               "judge": settings.nli_model, "threshold": args.threshold}

    print(f"\n{'':24}{'closed book':>14}{'rag':>14}")
    for k in ("grounded_claims", "answers_fully_grounded", "gold_numbers_present", "answered"):
        print(f"{k:24}{str(summary['closed_book'][k]):>14}{str(summary['rag'][k]):>14}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"summary": summary, "cases": rows},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
