"""An LLM judge for claims: the second instrument, independent of the guard.

    python -m eval.judge run reports/runs/<run>/*.json --model openai/gpt-oss-120b \\
        --base-url https://api.groq.com/openai/v1 --api-key-env GROQ_API_KEY
    python -m eval.judge calibrate reports/grading/hand-graded.json --model ...

The NLI instrument is the guard's own model at the guard's own threshold, so
it cannot say when the guard is wrong. The judge reads each claim next to the
passages the answer cited - the same claims the instrument scores, so the two
can be compared claim for claim - and returns structured output per claim:
{verdict, error_type, rationale}, with error types taken from the failures
the hand-graded sample actually showed.

The judge never belongs to the model family that wrote the answers: a model
grading its own family shares its blind spots. `calibrate` scores the judge
and the NLI instrument against the hand-graded answers (Cohen's κ), which is
what says how far either can be trusted on the questions nobody graded.

Judging is resumable: a case already judged by the same model is skipped, a
case whose judging failed is tried again, and the report is saved after every
case. MAX_FAILURES failures in a row mean a spent quota: judging stops (exit 3)
instead of marking every remaining case as failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from eval.metrics import _mean
from eval.stats import cohen_kappa
from grounded_rag.generation.llm_client import LLMUnavailable, OpenAICompatClient

VERDICTS = ("supported", "unsupported", "contradicted")
ERROR_TYPES = ("none", "wrong_number", "wrong_subject", "missing_condition", "outdated_law",
               "not_in_source", "other")
# Free tiers cap tokens per minute; a judge prompt carries whole clauses, so a
# 429 means "wait", not "fail".
RATE_LIMIT_WAIT_S = 30.0
RATE_LIMIT_TRIES = 8
MAX_FAILURES = 5
QUOTA_EXIT = 3
FAMILIES = {"qwen": "qwen", "llama": "llama", "gpt": "openai", "o1": "openai", "o3": "openai",
            "o4": "openai", "openai": "openai", "gemini": "google", "gemma": "google",
            "claude": "anthropic", "mistral": "mistral", "mixtral": "mistral",
            "deepseek": "deepseek", "phi": "microsoft", "kimi": "moonshot"}

SYSTEM = """Bạn là người thẩm định pháp lý. Với mỗi mệnh đề, chỉ dựa vào các đoạn văn bản pháp luật được cung cấp (không dùng hiểu biết riêng), hãy quyết định:
- "supported": mọi chi tiết của mệnh đề (con số, chủ thể, điều kiện, phạm vi) đều có trong đoạn được trích.
- "contradicted": đoạn được trích nói khác với mệnh đề.
- "unsupported": đoạn được trích không đủ để chứng minh mệnh đề.
error_type là một trong: none, wrong_number, wrong_subject, missing_condition, outdated_law, not_in_source, other.
Chỉ trả về JSON, không thêm chữ nào khác, theo đúng dạng:
{"claims": [{"id": 1, "verdict": "...", "error_type": "...", "rationale": "một câu ngắn"}]}"""


def family(model: str) -> str:
    name = model.lower().split("/")[-1]
    for key, fam in FAMILIES.items():
        if name.startswith(key) or f"/{key}" in model.lower():
            return fam
    return name.split("-")[0]


def prompt(claims: list[dict], sources: dict[str, str]) -> str:
    parts = ["Các đoạn văn bản pháp luật:"]
    parts += [f"[{label}] {text}" for label, text in sources.items()]
    parts.append("\nCác mệnh đề cần thẩm định:")
    for i, c in enumerate(claims, start=1):
        cited = ", ".join(c.get("citations") or []) or "không trích dẫn"
        parts.append(f"{i}. ({cited}) {c['text']}")
    return "\n".join(parts)


def parse(text: str, n: int) -> list[dict]:
    """The judge's JSON, validated: one verdict per claim, known values only."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in the judge's reply")
    items = json.loads(match.group(0))["claims"]
    if len(items) != n:
        raise ValueError(f"{len(items)} verdicts for {n} claims")
    out = []
    for item in sorted(items, key=lambda x: x["id"]):
        verdict = item["verdict"]
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}")
        error = item.get("error_type", "other")
        out.append({"verdict": verdict,
                    "error_type": error if error in ERROR_TYPES else "other",
                    "rationale": str(item.get("rationale", ""))[:400]})
    return out


async def judge_claims(client: OpenAICompatClient, claims: list[dict],
                       sources: dict[str, str]) -> list[dict]:
    user = prompt(claims, sources)
    for attempt in range(2):
        reply = await _complete(client, user)
        try:
            return parse(reply.text, len(claims))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            if attempt:
                raise ValueError(f"unparseable judge reply: {e}") from e
            user += "\n\nChỉ trả về đúng một đối tượng JSON theo dạng đã cho."
    raise AssertionError("unreachable")


async def _complete(client: OpenAICompatClient, user: str):
    for attempt in range(RATE_LIMIT_TRIES):
        try:
            return await client.complete(SYSTEM, user, temperature=0.0, max_tokens=2500)
        except LLMUnavailable as e:
            if "429" not in str(e) or attempt == RATE_LIMIT_TRIES - 1:
                raise
            await asyncio.sleep(RATE_LIMIT_WAIT_S)
    raise AssertionError("unreachable")


def case_sources(case: dict) -> dict[str, str]:
    return {s["label"]: s["text"] for s in case["sources"] if s["label"] in case.get("cited", [])}


def judge_value(case: dict) -> float | None:
    """Per-question value for judge_hallucination_rate, on the same denominator
    as hallucination_rate: every question, an abstention counting as clean."""
    if case["status"] not in ("answered", "partial"):
        return 0.0
    judged = case.get("judge")
    if not judged or judged.get("hallucinated") is None:
        return None
    return float(judged["hallucinated"])


async def run_reports(paths: list[Path], client: OpenAICompatClient, model: str,
                      limit: int | None) -> None:
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        generator = (report.get("generator") or {}).get("model", "")
        if family(generator) == family(model):
            raise SystemExit(f"{path}: judge {model} is the same family as generator {generator}")
        todo = [c for c in report["cases"] if c["status"] in ("answered", "partial")
                and ((c.get("judge") or {}).get("model") != model or "error" in c["judge"])]
        failures = 0
        for k, case in enumerate(todo[:limit] if limit else todo, start=1):
            claims = case.get("claims", [])
            try:
                verdicts = (await judge_claims(client, claims, case_sources(case))
                            if claims else [])
                case["judge"] = {"model": model, "claims": verdicts,
                                 "hallucinated": any(v["verdict"] != "supported" for v in verdicts)}
            except Exception as e:  # noqa: BLE001 - one bad reply must not lose the run
                case["judge"] = {"model": model, "error": str(e)[:300], "hallucinated": None}
                failures += 1
            else:
                failures = 0
            case.setdefault("scores", {})["judge_hallucination_rate"] = judge_value(case)
            for c in report["cases"]:
                c.setdefault("scores", {})["judge_hallucination_rate"] = judge_value(c)
            report["metrics"]["judge_hallucination_rate"] = _mean(
                c["scores"]["judge_hallucination_rate"] for c in report["cases"]
                if c["scores"].get("judge_hallucination_rate") is not None)
            report["llm_judge"] = {"model": model, "family": family(model)}
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
            print(f"[judge] {path.name} {k}/{len(todo)} {case['id']} "
                  f"hallucinated={case['judge']['hallucinated']}", flush=True)
            if failures >= MAX_FAILURES:
                print(f"[stop] {failures} judge calls in a row failed; rerun to resume", flush=True)
                raise SystemExit(QUOTA_EXIT)


async def calibrate(sheet_path: Path, client: OpenAICompatClient, model: str,
                    out: Path) -> dict:
    """Judge every hand-graded answer, then compare judge and NLI with the grades."""
    rows = json.loads(sheet_path.read_text(encoding="utf-8"))
    human, judge, nli, details = [], [], [], []
    for r in rows:
        claims = [{"text": text, "citations": list(r["cited"])} for text, _, _ in r["claims"]]
        verdicts = await judge_claims(client, claims, r["cited"]) if claims else []
        judged_wrong = any(v["verdict"] != "supported" for v in verdicts)
        human.append("wrong" if r["grade"] == "wrong" else "not_wrong")
        judge.append("wrong" if judged_wrong else "not_wrong")
        nli.append("wrong" if r["instrument_hallucinated"] else "not_wrong")
        details.append({"config": r["config"], "id": r["id"], "grade": r["grade"],
                        "judge_wrong": judged_wrong, "nli_wrong": r["instrument_hallucinated"],
                        "verdicts": verdicts})
        print(f"[calibrate] {r['config']}:{r['id']} grade={r['grade']} judge_wrong={judged_wrong}",
              flush=True)
    summary = {
        "judge_model": model, "n": len(rows),
        "kappa_judge_vs_grades": cohen_kappa(human, judge),
        "kappa_nli_vs_grades": cohen_kappa(human, nli),
        "judge_flags": judge.count("wrong"), "nli_flags": nli.count("wrong"),
        "graded_wrong": human.count("wrong"),
        "judge_catches": sum(h == j == "wrong" for h, j in zip(human, judge, strict=True)),
        "nli_catches": sum(h == n == "wrong" for h, n in zip(human, nli, strict=True)),
        "answers": details,
    }
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "answers"}, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "calibrate"])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    ap.add_argument("--reasoning-effort", default="")
    ap.add_argument("--limit", type=int, help="run: at most this many new cases per report")
    ap.add_argument("--out", type=Path, default=Path("reports/grading/judge-agreement.json"))
    args = ap.parse_args()
    key = os.environ.get(args.api_key_env, "")
    if not key:
        raise SystemExit(f"set {args.api_key_env}")
    client = OpenAICompatClient(args.base_url, key, args.model,
                                reasoning_effort=args.reasoning_effort)
    if args.step == "run":
        asyncio.run(run_reports(args.paths, client, args.model, args.limit))
    else:
        asyncio.run(calibrate(args.paths[0], client, args.model, args.out))


if __name__ == "__main__":
    main()
