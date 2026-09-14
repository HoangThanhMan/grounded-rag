import pytest

from eval.metrics import Case, Row, aggregate, citation_precision_recall, covers, hallucinated
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
