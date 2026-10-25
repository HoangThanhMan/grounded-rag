"""The benchmark harness has to outlive a flaky provider.

A single 503 on question 40 used to abort the run and write nothing, losing
every question before it. These tests pin the behaviour that replaced it.
"""

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

import eval.run as runner
from eval.instrument import ClauseIndex
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.ingest.pipeline import ingest

SAMPLE = Path("data/sample_corpus")
DATASET = Path("eval/dataset/questions.sample.jsonl")


@pytest.fixture(scope="module")
def indexed():
    config = RunConfig.from_yaml("configs/full.yaml")
    ingest(SAMPLE, config)
    return config


def _report(config, monkeypatch, fail_ids):
    """Run the harness with the provider failing for the listed question ids."""
    real = runner.answer_question
    ids = {json.loads(line)["question"]: json.loads(line)["id"]
           for line in DATASET.read_text(encoding="utf-8").splitlines() if line}

    async def flaky(question, cfg, **kw):
        if ids.get(question) in fail_ids:
            raise LLMUnavailable("HTTP 503: high demand")
        return await real(question, cfg, **kw)

    monkeypatch.setattr(runner, "answer_question", flaky)
    monkeypatch.setattr(runner, "_CASE_BACKOFF_S", 0.0)
    return asyncio.run(runner.run(config, DATASET, ClauseIndex(SAMPLE), 0.6, date(2026, 9, 14)))


def test_a_failing_question_does_not_lose_the_run(indexed, monkeypatch):
    report = _report(indexed, monkeypatch, {"a002"})
    assert [e["id"] for e in report["errored"]] == ["a002"]
    assert "a002" not in [c["id"] for c in report["cases"]]
    # every other question still made it into the report
    assert len(report["cases"]) == 5
    assert report["metrics"]["n"] == 5


def test_a_healthy_run_reports_nothing_errored(indexed, monkeypatch):
    report = _report(indexed, monkeypatch, set())
    assert report["errored"] == []
    assert len(report["cases"]) == 6


def test_a_temporal_question_is_asked_on_its_own_date(indexed, monkeypatch, tmp_path):
    lines = DATASET.read_text(encoding="utf-8").splitlines()[:2]
    first, second = json.loads(lines[0]), json.loads(lines[1])
    first["as_of"] = "2024-06-01"
    dataset = tmp_path / "two.jsonl"
    dataset.write_text(json.dumps(first, ensure_ascii=False) + "\n"
                       + json.dumps(second, ensure_ascii=False) + "\n", encoding="utf-8")
    asked = {}
    real = runner.answer_question

    async def spy(question, cfg, **kw):
        asked[question] = kw["as_of"]
        return await real(question, cfg, **kw)

    monkeypatch.setattr(runner, "answer_question", spy)
    report = asyncio.run(runner.run(indexed, dataset, ClauseIndex(SAMPLE), 0.6, date(2026, 9, 14)))
    assert asked[first["question"]] == date(2024, 6, 1)
    assert asked[second["question"]] == date(2026, 9, 14)
    assert [c["as_of"] for c in report["cases"]] == ["2024-06-01", None]
