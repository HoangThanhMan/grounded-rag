from datetime import date

from grounded_rag.types import DocMeta
from scripts import check_dataset as cd


def _row(qid, split, group, gold=(), **kw):
    return {"id": qid, "split": split, "article_group": group, "gold_chunks": list(gold),
            "type": "answerable", "tags": [], **kw}


def test_an_article_group_split_across_dev_and_test_is_an_error():
    rows = [_row("a900", "dev", "law:Điều 1", ["law:Điều 1:1"]),
            _row("a901", "test", "law:Điều 1", ["law:Điều 1:2"])]
    errors = []
    cd.check_split(rows, errors)
    assert any("in both splits" in e for e in errors)


def test_one_article_in_two_groups_is_an_error():
    rows = [_row("a900", "test", "g1", ["law:Điều 1:1"]),
            _row("a901", "test", "g2", ["law:Điều 1:2"])]
    errors = []
    cd.check_split(rows, errors)
    assert any("spans groups" in e for e in errors)


def _temporal(qid, as_of, answer, gold):
    return _row(qid, "test", "pair", gold, tags=["temporal"], temporal_pair="p", as_of=as_of,
                question="Trợ cấp mai táng là bao nhiêu?", gold_answer=answer)


VALIDITY = {"old": DocMeta(effective_date=date(2016, 1, 1), expiry_date=date(2025, 7, 1)),
            "new": DocMeta(effective_date=date(2025, 7, 1))}


def test_a_well_formed_temporal_pair_passes(monkeypatch):
    monkeypatch.setattr(cd, "MIN_TEMPORAL", 2)
    rows = [_temporal("a900", "2024-06-01", "10 lần mức lương cơ sở", ["old:Điều 66"]),
            _temporal("a901", "2025-09-01", "10 lần mức tham chiếu", ["new:Điều 85:2"])]
    errors = []
    cd.check_temporal(rows, VALIDITY, errors)
    assert errors == []


def test_gold_not_in_force_on_the_date_asked_is_an_error(monkeypatch):
    monkeypatch.setattr(cd, "MIN_TEMPORAL", 2)
    # the old law asked about after it expired - the boundary day is already too late
    rows = [_temporal("a900", "2025-07-01", "10 lần mức lương cơ sở", ["old:Điều 66"]),
            _temporal("a901", "2025-09-01", "10 lần mức tham chiếu", ["new:Điều 85:2"])]
    errors = []
    cd.check_temporal(rows, VALIDITY, errors)
    assert any("not in force on 2025-07-01" in e for e in errors)


def test_a_pair_with_the_same_answer_twice_is_an_error(monkeypatch):
    monkeypatch.setattr(cd, "MIN_TEMPORAL", 2)
    rows = [_temporal("a900", "2024-06-01", "05 lần", ["old:Điều 32"]),
            _temporal("a901", "2025-09-01", "05 lần", ["new:Điều 51:1"])]
    errors = []
    cd.check_temporal(rows, VALIDITY, errors)
    assert any("two answers" in e for e in errors)
