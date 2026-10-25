import pytest

from eval.metrics import (
    Case,
    Row,
    aggregate,
    answer_correct,
    case_scores,
    citation_precision_recall,
    covers,
    hallucinated,
    recall_at,
    reciprocal_rank,
)
from grounded_rag.types import (
    AbstainReason,
    Answer,
    AnswerStatus,
    Chunk,
    Claim,
    RetrievedChunk,
    Verdict,
)

REF = "bllđ:Điều 35:1"
GOLD_TEXT = {
    REF: "1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động "
    "nhưng phải báo trước ít nhất 45 ngày."
}


def _src(label: str, text: str, **kw) -> RetrievedChunk:
    chunk = Chunk(chunk_id=f"bllđ:{label}", doc_id="bllđ", text=text, **kw)
    return RetrievedChunk(chunk=chunk, score=0.9, label=label)


def test_recursive_window_containing_the_gold_clause_is_a_hit():
    window = (
        "... Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động\n"
        f"{GOLD_TEXT[REF]}\n2. Người lao động không phải báo trước trong trường hợp ..."
    )
    answer = Answer(answer="Phải báo trước 45 ngày [C1].", status=AnswerStatus.ANSWERED,
                    sources=[_src("C1", window)])
    assert citation_precision_recall(answer, [REF], GOLD_TEXT) == (1.0, 1.0)


def test_structural_chunk_matches_by_ref_even_without_gold_text():
    src = _src("C1", "Điều 35. ...", article="Điều 35", clause="Khoản 1")
    answer = Answer(answer="Phải báo trước 45 ngày [C1].", status=AnswerStatus.ANSWERED,
                    sources=[src])
    assert citation_precision_recall(answer, [REF], {}) == (1.0, 1.0)


def test_a_different_clause_does_not_cover_the_gold_one():
    other = "Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày."
    assert not covers(other, GOLD_TEXT[REF])


def test_shared_boilerplate_is_not_containment():
    # overlap measures said this window "contained" the short clause
    window = "Người sử dụng lao động có trách nhiệm trả lương cho người lao động đúng hạn."
    clause = "Người sử dụng lao động có quyền đơn phương chấm dứt hợp đồng lao động."
    assert not covers(window, clause)


def test_half_of_a_long_clause_cut_by_the_window_still_counts():
    long_clause = " ".join(f"từ{i}" for i in range(40))
    first_half = " ".join(f"từ{i}" for i in range(20))
    assert covers(f"đầu cửa sổ {first_half}", long_clause)
    assert not covers(f"đầu cửa sổ {first_half}", long_clause, whole_only=True)


def test_citations_in_claims_the_guard_dropped_do_not_count():
    answer = Answer(
        answer="Phải báo trước 45 ngày [C1].",
        status=AnswerStatus.PARTIAL,
        sources=[_src("C1", GOLD_TEXT[REF]), _src("C2", "Tiền lương tối thiểu vùng.")],
        claims=[Claim(text="Được thưởng.", citations=["C2"], verdict=Verdict.UNSUPPORTED)],
    )
    precision, _ = citation_precision_recall(answer, [REF], GOLD_TEXT)
    assert precision == 1.0


def test_hallucination_is_read_from_the_eval_verdicts_not_the_pipeline():
    # guard off: the pipeline left the claim unverified
    answer = Answer(answer="X [C1].", status=AnswerStatus.ANSWERED,
                    claims=[Claim(text="X", citations=["C1"])])
    judged = [Claim(text="X", citations=["C1"], verdict=Verdict.UNSUPPORTED)]
    assert hallucinated(Row(case=Case(id="a", answerable=True), answer=answer, judged=judged))


def test_abstention_layers_add_up_to_correct_abstention():
    def row(status, reason):
        answer = Answer(answer="...", status=status)
        answer.meta.abstain_reason = reason
        case = Case(id="u", answerable=False, type="unanswerable_near_miss")
        return Row(case=case, answer=answer)

    m = aggregate([
        row(AnswerStatus.NO_CONTEXT, AbstainReason.RETRIEVAL_FLOOR),
        row(AnswerStatus.ABSTAINED, AbstainReason.MODEL),
        row(AnswerStatus.ABSTAINED, AbstainReason.GUARD),
        row(AnswerStatus.ANSWERED, None),
    ])
    assert m["correct_abstention"] == 0.75
    assert sum(m["correct_abstention_by_layer"].values()) == pytest.approx(0.75)
    assert m["by_type"]["unanswerable_near_miss"]["n"] == 4


OTHER = "Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày."


def _ranked(*texts: str) -> Answer:
    sources = [_src(f"C{i + 1}", t) for i, t in enumerate(texts)]
    return Answer(answer="...", status=AnswerStatus.ANSWERED, sources=sources)


def test_recall_at_k_counts_only_the_top_k_sources():
    answer = _ranked(OTHER, OTHER, GOLD_TEXT[REF])
    assert recall_at(answer, [REF], GOLD_TEXT, 1) == 0.0
    assert recall_at(answer, [REF], GOLD_TEXT, 3) == 1.0


def test_reciprocal_rank_is_one_over_the_first_hit():
    assert reciprocal_rank(_ranked(OTHER, GOLD_TEXT[REF]), [REF], GOLD_TEXT) == 0.5
    assert reciprocal_rank(_ranked(GOLD_TEXT[REF], OTHER), [REF], GOLD_TEXT) == 1.0
    assert reciprocal_rank(_ranked(OTHER), [REF], GOLD_TEXT) == 0.0


def test_answer_correct_needs_every_gold_number_and_ignores_citation_labels():
    def ans(text, status=AnswerStatus.ANSWERED):
        return Answer(answer=text, status=status)

    gold = "Ít nhất 45 ngày; 30 ngày với hợp đồng 12 đến 36 tháng."
    assert answer_correct(ans("Báo trước 45 ngày, hoặc 30 ngày (12-36 tháng) [C1]."), gold)
    assert not answer_correct(ans("Báo trước 45 ngày [C1]."), gold)
    # "08" in the statute, "8" in an answer: the same number
    assert answer_correct(ans("Không quá 8 giờ."), "Không quá 08 giờ.")
    # the 1 in [C1] is not the 01 the gold answer wants
    assert not answer_correct(ans("Một ngày [C1]."), "01 ngày.")
    assert not answer_correct(ans("...", AnswerStatus.ABSTAINED), "45 ngày.")
    assert answer_correct(ans("Không."), "Không phải đặt cọc.") is None


def test_each_rate_averages_only_over_the_questions_it_applies_to():
    answered = Answer(answer="Báo trước 45 ngày [C1].", status=AnswerStatus.ANSWERED,
                      sources=[_src("C1", GOLD_TEXT[REF])])
    refused = Answer(answer="...", status=AnswerStatus.NO_CONTEXT)
    rows = [
        Row(case=Case(id="a1", answerable=True, gold_chunks=[REF], gold_answer="45 ngày"),
            answer=answered),
        Row(case=Case(id="a2", answerable=True, gold_chunks=[REF], gold_answer="Không."),
            answer=refused),
        Row(case=Case(id="u1", answerable=False), answer=refused),
    ]
    scores = [case_scores(r, GOLD_TEXT) for r in rows]
    assert scores[2]["false_abstention"] is None and scores[0]["correct_abstention"] is None
    assert scores[1]["citation_precision"] is None  # nothing to cite from a refusal
    m = aggregate(rows, GOLD_TEXT)
    assert m["false_abstention"] == 0.5
    assert m["correct_abstention"] == 1.0
    assert m["citation_precision"] == 1.0
    assert m["answer_correctness"] == 1.0 and m["answer_correctness_n"] == 1
    assert m["recall_at_1"] == 0.5 and m["mrr"] == 0.5
