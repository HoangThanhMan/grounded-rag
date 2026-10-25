import json

import pytest

from scripts import hand_grade


def _case(i: int, *, flagged: bool = False, status: str = "answered") -> dict:
    return {
        "id": f"a{i:03d}", "type": "answerable", "question": f"q{i}", "gold_answer": "g",
        "answer": f"answer {i} [C1]", "status": status, "hallucinated": flagged,
        "claims": [{"text": f"answer {i}", "verdict": "supported", "entailment": 0.9}],
        "sources": [{"label": "C1", "text": "clause"}, {"label": "C2", "text": "unused"}],
        "cited": ["C1"],
    }


def _report(config: str, cases: list[dict]) -> dict:
    return {"config": config, "cases": cases}


def _reports() -> list[dict]:
    baseline = [_case(i, flagged=i < 5) for i in range(20)]
    full = [_case(i) for i in range(20)] + [_case(99, status="abstained")]
    return [_report("baseline", baseline), _report("full", full)]


def test_random_stratum_is_n_answered_cases_spread_across_reports():
    rows = hand_grade.draw(_reports(), n=10)
    random_rows = [r for r in rows if r["stratum"] == "random"]
    assert len(random_rows) == 10
    assert {r["config"] for r in random_rows} == {"baseline", "full"}
    assert all(r["status"] in ("answered", "partial") for r in random_rows)


def test_every_flagged_answer_is_on_the_sheet_exactly_once():
    rows = hand_grade.draw(_reports(), n=10)
    keys = [(r["config"], r["id"]) for r in rows]
    assert len(keys) == len(set(keys))
    flagged_on_sheet = {(r["config"], r["id"]) for r in rows if r["instrument_hallucinated"]}
    assert flagged_on_sheet == {("baseline", f"a{i:03d}") for i in range(5)}
    assert all(r["instrument_hallucinated"] for r in rows if r["stratum"] == "flagged")


def test_flagged_answer_drawn_at_random_stays_in_the_random_stratum():
    # every baseline case flagged and n large enough to take them all
    reports = [_report("baseline", [_case(i, flagged=True) for i in range(4)])]
    rows = hand_grade.draw(reports, n=4)
    assert [r["stratum"] for r in rows] == ["random"] * 4


def test_draw_is_reproducible_and_keeps_only_cited_sources():
    first, second = hand_grade.draw(_reports(), n=10), hand_grade.draw(_reports(), n=10)
    assert first == second
    assert all(set(r["cited"]) == {"C1"} for r in first)
    assert all(r["grade"] is None for r in first)


def test_sample_refuses_to_draw_over_a_graded_sheet(tmp_path, monkeypatch):
    sheet = tmp_path / "hand-graded.json"
    monkeypatch.setattr(hand_grade, "SHEET", sheet)
    report = tmp_path / "baseline.json"
    report.write_text(json.dumps(_reports()[0]), encoding="utf-8")

    hand_grade.sample([report])
    rows = json.loads(sheet.read_text(encoding="utf-8"))
    rows[0]["grade"] = "correct"
    sheet.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(SystemExit, match="already has 1 grades"):
        hand_grade.sample([report])
    hand_grade.sample([report], force=True)
    assert all(r["grade"] is None for r in json.loads(sheet.read_text(encoding="utf-8")))
