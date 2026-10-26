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


def test_one_cell_can_be_selected_and_stops_on_a_spent_quota(monkeypatch, tmp_path):
    spec = dict(SPEC, out=str(tmp_path), judge=None)
    monkeypatch.setattr(matrix.yaml, "safe_load", lambda _: spec)
    ran = []

    def fake_run(cell, spec):
        ran.append((cell["config"], cell["seed"]))
        return 3  # the quota is spent: no report

    monkeypatch.setattr(matrix, "run_cell", fake_run)
    monkeypatch.setattr(matrix.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["matrix", "eval/matrix.yaml", "--only-config", "full",
                                     "--only-seed", "2"])
    assert matrix.main() == 1
    assert ran == [("full", 2)]
