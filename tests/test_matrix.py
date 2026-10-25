import json
from pathlib import Path

import yaml

from eval import matrix

SPEC = yaml.safe_load(Path("eval/matrix.yaml").read_text(encoding="utf-8"))


def test_cells_run_seed_by_seed():
    cells = matrix.cells(SPEC)
    assert len(cells) == len(SPEC["seeds"]) * len(SPEC["configs"]) * len(SPEC["generators"])
    first_round = cells[: len(SPEC["configs"])]
    assert {c["seed"] for c in first_round} == {SPEC["seeds"][0]}
    assert [c["config"] for c in first_round] == SPEC["configs"]


def test_a_report_with_errored_cases_is_not_done(tmp_path):
    path = tmp_path / "full.s1.json"
    assert not matrix.done(path)
    path.write_text(json.dumps({"errored": [{"id": "a001"}]}))
    assert not matrix.done(path)
    path.write_text(json.dumps({"errored": []}))
    assert matrix.done(path)


def test_the_generator_reaches_eval_run_through_the_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    env = matrix.env_for(SPEC["generators"][0], SPEC)
    assert env["LLM_PROVIDER"] == "openai" and env["OPENAI_API_KEY"] == "k"
    assert env["OPENAI_BASE_URL"].startswith("https://")
    assert env["RETRIEVAL_CACHE_DIR"] == SPEC["retrieval_cache"]
    assert env["LANGFUSE_PUBLIC_KEY"] == ""


def test_the_judge_is_not_the_generators_family():
    from eval.judge import family
    assert all(family(g["model"]) != family(SPEC["judge"]["model"]) for g in SPEC["generators"])
