"""The one evaluation: which questions it asks, and how an answer is scored."""

import asyncio
import json
from datetime import date
from pathlib import Path

from eval.gold import gold_text
from eval.run import run, score, select_cases
from grounded_rag.ingest.loaders import load_file
from grounded_rag.ingest.pipeline import ingest_file
from grounded_rag.types import Answer, AnswerStatus, Chunk, RetrievedChunk

SAMPLE = Path("data/sample_corpus")
GOLD = gold_text(SAMPLE)
DATASET = [json.loads(line) for line in Path("eval/questions.jsonl").read_text().splitlines()]

NOTICE_CASE = {
    "id": "t1",
    "question": "Nghỉ việc phải báo trước bao nhiêu ngày?",
    "answerable": True,
    "gold_answer": "Ít nhất 45 ngày.",
    "gold_chunks": ["bo_luat_lao_dong_2019:Điều 35:1"],
    "type": "answerable",
}
UNANSWERABLE = {"id": "t2", "question": "Thuế thu nhập cá nhân?", "answerable": False,
                "gold_answer": None, "gold_chunks": [], "type": "unanswerable_out_of_scope"}


def _answer(text: str, cited_ref: str, status=AnswerStatus.ANSWERED) -> Answer:
    article, clause = cited_ref.split(":")[1:]
    chunk = Chunk(chunk_id="x", doc_id="bo_luat_lao_dong_2019", text=GOLD.get(cited_ref, "..."),
                  article=article, clause=f"Khoản {clause}")
    src = RetrievedChunk(chunk=chunk, score=0.9, label="C1")
    citations = ["C1"] if status is AnswerStatus.ANSWERED else []
    return Answer(answer=text, status=status, sources=[src], citations=citations)


def test_select_cases_is_stratified_and_stable():
    cases = select_cases(DATASET)
    assert len(cases) == 100
    types = [c["type"] for c in cases]
    assert types.count("answerable") == 60
    assert types.count("unanswerable_out_of_scope") == 13
    assert types.count("unanswerable_false_premise") == 13
    assert types.count("unanswerable_near_miss") == 14
    assert all(c["split"] == "test" for c in cases)
    assert [c["id"] for c in select_cases(DATASET)] == [c["id"] for c in cases]


def test_score_correct_needs_the_gold_clause_and_the_numbers():
    right = _answer("Ít nhất 45 ngày [C1].", "bo_luat_lao_dong_2019:Điều 35:1")
    wrong_clause = _answer("Ít nhất 45 ngày [C1].", "bo_luat_lao_dong_2019:Điều 105:1")
    wrong_number = _answer("Ít nhất 30 ngày [C1].", "bo_luat_lao_dong_2019:Điều 35:1")
    assert score(NOTICE_CASE, right, GOLD)["correct"] is True
    assert score(NOTICE_CASE, wrong_clause, GOLD)["correct"] is False
    assert score(NOTICE_CASE, wrong_number, GOLD)["correct"] is False
    assert score(NOTICE_CASE, right, GOLD)["hit_at_5"] is True
    assert score(NOTICE_CASE, wrong_clause, GOLD)["hit_at_5"] is False


def test_refusal_scores():
    refused = _answer("Không tìm thấy thông tin này trong tài liệu.",
                      "bo_luat_lao_dong_2019:Điều 35:1", AnswerStatus.ABSTAINED)
    on_answerable = score(NOTICE_CASE, refused, GOLD)
    assert (on_answerable["false_refusal"], on_answerable["correct"]) == (True, False)
    assert on_answerable["correct_refusal"] is None
    on_unanswerable = score(UNANSWERABLE, refused, GOLD)
    assert on_unanswerable == {"hit_at_5": None, "correct": None, "false_refusal": None,
                               "correct_refusal": True}


def test_run_resumes(tmp_path):
    path = SAMPLE / "bo_luat_lao_dong_2019.md"
    ingest_file(path, "bo_luat_lao_dong_2019", load_file(path).meta)
    cases = [NOTICE_CASE, UNANSWERABLE, {**NOTICE_CASE, "id": "t3"}]
    out = tmp_path / "app.jsonl"
    asyncio.run(run("app", cases[:2], out, date(2026, 10, 28), GOLD))
    asyncio.run(run("app", cases, out, date(2026, 10, 28), GOLD))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
    assert {"status", "answer", "sources", "correct", "hit_at_5"} <= rows[0].keys()


def test_report_counts_each_column_over_its_own_questions():
    from eval.report import table

    rows = {
        "naive": [
            {"hit_at_5": True, "correct": True, "false_refusal": False, "correct_refusal": None},
            {"hit_at_5": False, "correct": False, "false_refusal": True, "correct_refusal": None},
            {"hit_at_5": None, "correct": None, "false_refusal": None, "correct_refusal": False},
        ],
        "app": [
            {"hit_at_5": True, "correct": True, "false_refusal": False, "correct_refusal": None},
            {"hit_at_5": True, "correct": True, "false_refusal": False, "correct_refusal": None},
            {"hit_at_5": None, "correct": None, "false_refusal": None, "correct_refusal": True},
        ],
    }
    out = table(rows)
    assert "0.50 (1/2)" in out          # naive hit@5 and correct
    assert "1.00 (2/2)" in out          # app hit@5 and correct
    assert "0.00 (0/1)" in out          # naive correct refusal
    assert out.count("\n|") == 3        # header rule + two systems
