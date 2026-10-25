import json
from datetime import date

import pytest

from scripts import agreement


def test_kappa_is_one_for_identical_labels_and_zero_for_chance():
    assert agreement.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    # both say "a" half the time, independently: agreement is what chance predicts
    assert agreement.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0


def test_kappa_matches_a_worked_example():
    # 20 items, 15 agreements; p_o = 0.75, p_e = 0.5 -> kappa 0.5
    first = ["y"] * 10 + ["n"] * 10
    second = ["y"] * 8 + ["n"] * 2 + ["y"] * 3 + ["n"] * 7
    assert agreement.cohen_kappa(first, second) == pytest.approx(0.5, abs=0.01)


def test_draw_keeps_each_type_in_proportion():
    rows = ([{"id": f"a{i}", "type": "answerable"} for i in range(180)]
            + [{"id": f"u{i}", "type": t} for t in agreement.TYPES[1:] for i in range(40)])
    picked = agreement.draw(rows)
    counts = {t: sum(r["type"] == t for r in picked) for t in agreement.TYPES}
    assert counts == {"answerable": 36, "unanswerable_out_of_scope": 8,
                      "unanswerable_false_premise": 8, "unanswerable_near_miss": 8}


def test_an_intra_relabel_cannot_be_scored_before_the_wait(tmp_path, monkeypatch):
    sheet = tmp_path / "relabel.json"
    sheet.write_text(json.dumps({"annotator": "intra", "drawn_on": "2026-10-20", "rows": []}))
    monkeypatch.setattr(agreement, "SHEET", sheet)
    with pytest.raises(SystemExit, match="wait 10"):
        agreement.score(today=date(2026, 10, 25))
