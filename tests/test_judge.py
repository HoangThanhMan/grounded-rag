import asyncio
import json

import httpx
import pytest

from eval import judge
from grounded_rag.generation.llm_client import OpenAICompatClient


def test_model_families():
    assert judge.family("qwen/qwen3.8-27b") == "qwen"
    assert judge.family("openai/gpt-oss-120b") == "openai"
    assert judge.family("gemini-3.1-flash-lite") == "google"
    assert judge.family("claude-haiku-5-5") == "anthropic"


def test_parse_validates_one_known_verdict_per_claim():
    reply = ('Kết quả: {"claims": [{"id": 2, "verdict": "contradicted", "error_type": '
             '"wrong_number", "rationale": "luật nói 45 ngày"}, {"id": 1, "verdict": '
             '"supported", "error_type": "none", "rationale": "khớp"}]}')
    out = judge.parse(reply, 2)
    assert [v["verdict"] for v in out] == ["supported", "contradicted"]
    assert out[1]["error_type"] == "wrong_number"
    with pytest.raises(ValueError):
        judge.parse(reply, 3)
    with pytest.raises(ValueError):
        judge.parse('{"claims": [{"id": 1, "verdict": "maybe"}]}', 1)


def _client(replies):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        text = replies.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": text},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    client = OpenAICompatClient("http://judge", "k", "openai/gpt-oss-120b",
                                transport=httpx.MockTransport(handler), retries=0)
    return client, calls


def _report(tmp_path, generator="qwen/qwen3.8-27b"):
    report = {"config": "full", "generator": {"model": generator}, "metrics": {},
              "cases": [
                  {"id": "a1", "status": "answered", "cited": ["C1"],
                   "sources": [{"label": "C1", "text": "Phải báo trước ít nhất 45 ngày."}],
                   "claims": [{"text": "Phải báo trước 30 ngày.", "citations": ["C1"]}],
                   "scores": {}},
                  {"id": "u1", "status": "no_context", "cited": [], "sources": [], "claims": [],
                   "scores": {}}]}
    path = tmp_path / "full.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_judging_a_report_stores_verdicts_and_a_rate(tmp_path):
    path = _report(tmp_path)
    reply = ('{"claims": [{"id": 1, "verdict": "contradicted", "error_type": "wrong_number", '
             '"rationale": "45"}]}')
    client, calls = _client([reply])
    asyncio.run(judge.run_reports([path], client, "openai/gpt-oss-120b", None))
    report = json.loads(path.read_text(encoding="utf-8"))
    case = report["cases"][0]
    assert case["judge"]["hallucinated"] is True
    assert case["judge"]["claims"][0]["error_type"] == "wrong_number"
    # the abstention counts as clean, like hallucination_rate
    assert report["metrics"]["judge_hallucination_rate"] == 0.5
    assert "Phải báo trước ít nhất 45 ngày." in calls[0]["messages"][1]["content"]
    # a second pass with the same model has nothing left to judge
    asyncio.run(judge.run_reports([path], client, "openai/gpt-oss-120b", None))
    assert len(calls) == 1


def test_a_judge_from_the_generator_family_is_refused(tmp_path):
    path = _report(tmp_path, generator="openai/gpt-oss-20b")
    client, _ = _client([])
    with pytest.raises(SystemExit, match="same family"):
        asyncio.run(judge.run_reports([path], client, "openai/gpt-oss-120b", None))
