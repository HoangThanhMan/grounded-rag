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
                               "correct_refusal": True, "all_gold_retrieved": None,
                               "complete": None, "cites_wrong_scheme": None}


def _cited(text: str, *refs: str) -> Answer:
    """An answer citing one source per ref, C1, C2, ... in order."""
    sources = []
    for i, ref in enumerate(refs):
        article, clause = ref.split(":")[1:]
        chunk = Chunk(chunk_id=f"x{i}", doc_id="bo_luat_lao_dong_2019", text=GOLD[ref],
                      article=article, clause=f"Khoản {clause}")
        sources.append(RetrievedChunk(chunk=chunk, score=0.9, label=f"C{i + 1}"))
    return Answer(answer=text, status=AnswerStatus.ANSWERED, sources=sources,
                  citations=[s.label for s in sources])


BOTH_SIDES = {
    "id": "h1",
    "question": "Nghỉ việc báo trước bao lâu, và được nghỉ phép năm bao nhiêu ngày?",
    "answerable": True,
    "gold_answer": "Ít nhất 45 ngày; 12 ngày phép năm.",
    "gold_chunks": ["bo_luat_lao_dong_2019:Điều 35:1", "bo_luat_lao_dong_2019:Điều 113:1"],
    "type": "multi_part",
}


def test_a_complete_answer_cites_every_gold_clause():
    half = _cited("Ít nhất 45 ngày, 12 ngày phép [C1].", "bo_luat_lao_dong_2019:Điều 35:1")
    whole = _cited("Ít nhất 45 ngày [C1], 12 ngày phép [C2].",
                   "bo_luat_lao_dong_2019:Điều 35:1", "bo_luat_lao_dong_2019:Điều 113:1")
    assert score(BOTH_SIDES, half, GOLD)["correct"] is True      # one gold clause is enough
    assert score(BOTH_SIDES, half, GOLD)["complete"] is False
    assert score(BOTH_SIDES, half, GOLD)["all_gold_retrieved"] is False
    assert score(BOTH_SIDES, whole, GOLD)["complete"] is True
    assert score(BOTH_SIDES, whole, GOLD)["all_gold_retrieved"] is True


def test_citing_a_clause_of_the_wrong_scheme_is_counted():
    trap = {**NOTICE_CASE, "type": "scheme_trap",
            "trap_chunks": ["bo_luat_lao_dong_2019:Điều 105:1"]}
    fell = _cited("Ít nhất 45 ngày [C1][C2].", "bo_luat_lao_dong_2019:Điều 35:1",
                  "bo_luat_lao_dong_2019:Điều 105:1")
    kept_clear = _cited("Ít nhất 45 ngày [C1].", "bo_luat_lao_dong_2019:Điều 35:1")
    assert score(trap, fell, GOLD)["cites_wrong_scheme"] is True
    assert score(trap, kept_clear, GOLD)["cites_wrong_scheme"] is False
    assert score(NOTICE_CASE, kept_clear, GOLD)["cites_wrong_scheme"] is None


def test_the_hard_set_is_asked_whole_and_apart_from_the_sample():
    hard = select_cases(DATASET, "hard")
    assert {c["split"] for c in hard} == {"hard"}
    assert {c["type"] for c in hard} == {"multi_part", "scheme_trap", "compare_versions"}
    assert all(c["answerable"] for c in hard)
    assert len(hard) == sum(r["split"] == "hard" for r in DATASET)


VERIFIED_2014 = {f"Điều {n}" for n in (29, 32, 33, 34, 38, 41, 66, 68)}


def test_every_hard_case_points_at_clauses_the_corpus_has():
    gold = gold_text(Path("data/corpus"))
    for case in select_cases(DATASET, "hard"):
        for ref in case["gold_chunks"] + case.get("trap_chunks", []):
            assert ref in gold, f"{case['id']}: no clause {ref}"
        if case["type"] == "scheme_trap":
            assert case["trap_chunks"], case["id"]
        # of the 2014 law, only articles never amended before 2025 (LABELING.md)
        for ref in case["gold_chunks"]:
            if ref.startswith("luat_bao_hiem_xa_hoi_2014:"):
                assert ref.split(":")[1] in VERIFIED_2014, f"{case['id']}: {ref} was amended"
        # matching reads text: a trap worded like a gold clause would score as both
        from eval.gold import covers

        for trap in case.get("trap_chunks", []):
            for ref in case["gold_chunks"]:
                assert not covers(gold[trap], gold[ref]), f"{case['id']}: {trap} reads as {ref}"
                assert not covers(gold[ref], gold[trap]), f"{case['id']}: {ref} reads as {trap}"


def test_run_resumes(tmp_path):
    path = SAMPLE / "bo_luat_lao_dong_2019.md"
    ingest_file(path, "bo_luat_lao_dong_2019", load_file(path).meta)
    cases = [NOTICE_CASE, UNANSWERABLE, {**NOTICE_CASE, "id": "t3"}]
    out = tmp_path / "app.jsonl"
    asyncio.run(run("app", cases[:2], out, date(2026, 10, 28), GOLD))
    asyncio.run(run("app", cases, out, date(2026, 10, 28), GOLD))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
    assert {"status", "answer", "sources", "correct", "hit_at_5", "model",
            "escalated"} <= rows[0].keys()


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


def test_the_report_says_how_often_a_stronger_model_was_asked():
    from eval.report import escalations

    rows = {"app": [{"escalated": False, "model": "cheap"}],
            "app_cascade": [{"escalated": True, "model": "strong"},
                            {"escalated": False, "model": "cheap"}]}
    assert escalations(rows) == ["app_cascade: 1/2 answers redone by strong"]


def test_the_hard_report_breaks_results_down_by_kind():
    from eval.report import hard_table

    rows = {"app": [
        {"type": "multi_part", "hit_at_5": True, "all_gold_retrieved": False, "correct": True,
         "complete": False, "false_refusal": False, "cites_wrong_scheme": None},
        {"type": "scheme_trap", "hit_at_5": True, "all_gold_retrieved": True, "correct": True,
         "complete": True, "false_refusal": False, "cites_wrong_scheme": True},
    ]}
    out = hard_table(rows)
    assert "multi_part (1)" in out and "scheme_trap (1)" in out
    assert "1.00 (1/1)" in out and "0.00 (0/1)" in out
    assert "–" in out                   # no trap in the multi-part row


def test_a_window_that_holds_part_of_a_long_clause_matches_it():
    """Matching is on text for both systems: a fixed-size window that holds a
    long run of a clause counts like the clause chunk's own piece does."""
    from eval.gold import RUN_WORDS, covers

    clause = " ".join(f"tu{i}" for i in range(200))
    window = "phần đầu " + " ".join(f"tu{i}" for i in range(150, 150 + RUN_WORDS)) + " phần sau"
    assert covers(window, clause)
    short_overlap = " ".join(f"tu{i}" for i in range(10))
    assert not covers(short_overlap, clause)


def test_matching_ignores_the_ref_and_reads_the_text():
    from eval.gold import matches

    wrong_text = Chunk(chunk_id="x", doc_id="bo_luat_lao_dong_2019", text="Điều 35\nkhác hẳn",
                       article="Điều 35", clause="Khoản 1")
    assert not matches(wrong_text, "bo_luat_lao_dong_2019:Điều 35:1", GOLD)
