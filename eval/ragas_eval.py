"""A second opinion on a report: the four RAGAS metrics, scored by an LLM judge.

    python -m eval.ragas_eval reports/full.json         # -> reports/full.ragas.json

Why, when eval/run.py already measures hallucination: that number comes from
the NLI model the guard itself uses, which is circular. RAGAS faithfulness is
judged by an LLM - a different model family - so the cases where the two
disagree are exactly the ones to read by hand.

The judge is any OpenAI-compatible endpoint (Gemini, Ollama, vLLM, OpenAI):

    JUDGE_MODEL=gemini-2.5-flash
    JUDGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
    JUDGE_API_KEY=...

Answer relevancy also needs embeddings; bge-m3 runs locally (EMBEDDING_MODEL).
Needs the `eval` and `models` extras.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path

from grounded_rag.config import settings
from grounded_rag.generation.citation import strip_citations

RECALL_OK = 0.5     # below: the evidence never reached the model
FAITHFUL_OK = 0.8   # below: the answer strays from the context it was given
ANSWERED = {"answered", "partial"}


def diagnose(context_recall: float | None, faithfulness: float | None) -> str:
    """Where to look first. Recall speaks for retrieval, faithfulness for generation."""
    if context_recall is None or faithfulness is None:
        return "n/a"
    retrieval_ok = context_recall >= RECALL_OK
    generation_ok = faithfulness >= FAITHFUL_OK
    if retrieval_ok and generation_ok:
        return "ok"
    if retrieval_ok:
        return "generation_unfaithful"   # right evidence, model strays: prompt / guard / model
    if generation_ok:
        return "retrieval_gap"           # faithful to thin evidence: chunking / embedding / rewrite
    return "both"


def summarize(scored: list[dict]) -> dict:
    judged = [s for s in scored if "skipped" not in s]

    def mean(key: str) -> float | None:
        vals = [s[key] for s in judged if s.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    # NLI instrument vs LLM judge, on "does this answer contain anything unsupported?"
    agreement: Counter[str] = Counter()
    for s in judged:
        if s.get("faithfulness") is None:
            continue
        judge_clean = s["faithfulness"] >= 0.999
        nli_clean = s["nli_clean"]
        if judge_clean and nli_clean:
            agreement["both_clean"] += 1
        elif not judge_clean and not nli_clean:
            agreement["both_flagged"] += 1
        elif nli_clean:
            agreement["only_judge_flagged"] += 1   # candidate guard misses - read these
        else:
            agreement["only_nli_flagged"] += 1     # guard stricter than the judge

    return {
        "n_judged": len(judged),
        "n_skipped": len(scored) - len(judged),
        "n_errors": sum(bool(s.get("errors")) for s in judged),
        "faithfulness": mean("faithfulness"),
        "answer_relevancy": mean("answer_relevancy"),
        "context_precision": mean("context_precision"),
        "context_recall": mean("context_recall"),
        "diagnosis": dict(Counter(s["diagnosis"] for s in judged)),
        "nli_vs_judge": dict(agreement),
    }


def _build_metrics() -> dict:
    from openai import AsyncOpenAI
    from ragas.embeddings import HuggingFaceEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    client = AsyncOpenAI(
        base_url=os.environ.get("JUDGE_BASE_URL") or None,
        api_key=os.environ.get("JUDGE_API_KEY") or "EMPTY",
    )
    llm = llm_factory(os.environ["JUDGE_MODEL"], client=client)
    embeddings = HuggingFaceEmbeddings(model=settings.embedding_model)
    return {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
        "context_precision": ContextPrecisionWithReference(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }


async def score_case(case: dict, metrics: dict, sem: asyncio.Semaphore) -> dict:
    out = {"id": case["id"], "type": case["type"], "status": case["status"]}
    if case["status"] not in ANSWERED or not case["sources"]:
        return {**out, "skipped": "no answer to judge"}

    question = case["question"]
    response = strip_citations(case["answer"])
    contexts = [s["text"] for s in case["sources"]]
    reference = case.get("gold_answer")

    jobs = {
        "faithfulness": lambda: metrics["faithfulness"].ascore(
            user_input=question, response=response, retrieved_contexts=contexts
        ),
        "answer_relevancy": lambda: metrics["answer_relevancy"].ascore(
            user_input=question, response=response
        ),
    }
    if reference:  # the two context metrics need a gold answer
        jobs["context_precision"] = lambda: metrics["context_precision"].ascore(
            user_input=question, reference=reference, retrieved_contexts=contexts
        )
        jobs["context_recall"] = lambda: metrics["context_recall"].ascore(
            user_input=question, retrieved_contexts=contexts, reference=reference
        )

    async with sem:
        for name, job in jobs.items():
            try:
                out[name] = round(float((await job()).value), 4)
            except Exception as e:  # one failed judgement must not sink the run
                out[name] = None
                out.setdefault("errors", {})[name] = f"{type(e).__name__}: {e}"[:200]

    out["diagnosis"] = diagnose(out.get("context_recall"), out.get("faithfulness"))
    out["nli_clean"] = not case["hallucinated"]
    return out


async def _score_all(cases: list[dict], metrics: dict, concurrency: int) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    return list(await asyncio.gather(*(score_case(c, metrics, sem) for c in cases)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path, help="a report written by eval.run")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    if not os.environ.get("JUDGE_MODEL"):
        raise SystemExit("set JUDGE_MODEL (and JUDGE_BASE_URL / JUDGE_API_KEY) - see the docstring")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    scored = asyncio.run(_score_all(report["cases"], _build_metrics(), args.concurrency))
    result = {
        "config": report["config"],
        "judge_model": os.environ["JUDGE_MODEL"],
        "summary": summarize(scored),
        "cases": scored,
    }

    out = args.out or args.report.with_suffix(".ragas.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), "utf-8")
    print(f"=== {result['config']} judged by {result['judge_model']} -> {out}")
    for k, v in result["summary"].items():
        print(f"  {k:20} {v}")


if __name__ == "__main__":
    main()
