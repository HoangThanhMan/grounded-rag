import pytest

from grounded_rag.config import GuardConfig
from grounded_rag.guard.policy import (
    apply_policy,
    is_abstention,
    regeneration_feedback,
    should_regenerate,
    verify_claims,
)
from grounded_rag.types import (
    ABSTAIN_TEXT,
    AnswerStatus,
    Chunk,
    Claim,
    RetrievedChunk,
    Verdict,
)


class FixedVerifier:
    def __init__(self, score):
        self.score = score

    def entailment(self, premise, hypothesis):
        return self.score


@pytest.fixture
def sources():
    chunk = Chunk(chunk_id="c1", doc_id="d", text="Phải báo trước ít nhất 45 ngày.")
    return [RetrievedChunk(chunk=chunk, score=0.9, label="C1")]


def test_supported_claim_passes_through(sources):
    claims = verify_claims("Phải báo trước 45 ngày [C1].", sources, FixedVerifier(0.9), 0.6)
    assert claims[0].verdict is Verdict.SUPPORTED
    assert apply_policy(claims, sources, GuardConfig(enabled=True)).status is AnswerStatus.ANSWERED


def test_unsupported_claim_is_dropped_not_shown(sources):
    claims = verify_claims("Phải báo trước 90 ngày [C1].", sources, FixedVerifier(0.1), 0.6)
    out = apply_policy(claims, sources, GuardConfig(enabled=True))
    assert out.status is AnswerStatus.ABSTAINED
    assert "90 ngày" not in out.answer


def test_a_claim_with_no_citation_can_never_be_supported(sources):
    claims = verify_claims("Một khẳng định không nguồn.", sources, FixedVerifier(1.0), 0.0)
    assert claims[0].verdict is Verdict.UNCITED


def test_partial_when_some_claims_survive(sources):
    claims = verify_claims(
        "Phải báo trước 45 ngày [C1]. Và được thưởng thêm [C1].",
        sources,
        FixedVerifier(0.9),
        0.6,
    )
    claims[1].verdict = Verdict.UNSUPPORTED
    out = apply_policy(claims, sources, GuardConfig(enabled=True))
    assert out.status is AnswerStatus.PARTIAL
    assert "thưởng thêm" not in out.answer


def test_regeneration_happens_once_then_stops(sources):
    claims = verify_claims("Sai hoàn toàn [C1].", sources, FixedVerifier(0.0), 0.6)
    cfg = GuardConfig(enabled=True, max_regenerations=1)
    assert should_regenerate(claims, cfg, attempts=1) is True
    assert should_regenerate(claims, cfg, attempts=2) is False


def test_guard_disabled_never_regenerates(sources):
    claims = verify_claims("Sai hoàn toàn [C1].", sources, FixedVerifier(0.0), 0.6)
    assert should_regenerate(claims, GuardConfig(enabled=False), attempts=1) is False


def test_the_models_own_refusal_is_recognised():
    assert is_abstention(ABSTAIN_TEXT)
    assert is_abstention("Xin lỗi, không tìm thấy thông tin này trong tài liệu")
    assert not is_abstention("Phải báo trước 45 ngày [C1].")
    # an answer that also admits a gap is still an answer, and gets verified
    assert not is_abstention(f"Phải báo trước 45 ngày [C1]. {ABSTAIN_TEXT}")


def test_baseline_does_not_drop_anything(sources):
    """With the guard off the answer must survive untouched - otherwise the
    baseline silently borrows the guard's benefit and the comparison lies."""
    raw = "Phải báo trước 90 ngày [C1]. Một khẳng định không nguồn."
    claims = verify_claims(raw, sources, FixedVerifier(0.0), 0.6)
    out = apply_policy(claims, sources, GuardConfig(enabled=False), raw_text=raw)
    assert out.status is AnswerStatus.ANSWERED
    assert out.answer == raw
    # verdicts are still reported, they just do not change the answer
    assert out.claims[1].verdict is Verdict.UNCITED


def test_no_surviving_claim_is_an_abstention_not_an_empty_answer():
    """A weak model can answer "[1]": an invalid citation that citation
    validation strips, leaving nothing. Reporting that as `answered` hands the
    caller an empty string dressed as a result."""
    for enabled in (True, False):
        out = apply_policy([], [], GuardConfig(enabled=enabled), raw_text="")
        assert out.status is AnswerStatus.ABSTAINED
        assert out.answer == ABSTAIN_TEXT


def test_guard_off_still_returns_the_model_text_verbatim():
    claims = [Claim(text="Báo trước 45 ngày.", citations=["C1"])]
    out = apply_policy(claims, [], GuardConfig(enabled=False), raw_text="Báo trước 45 ngày. [C1]")
    assert out.status is AnswerStatus.ANSWERED
    assert out.answer == "Báo trước 45 ngày. [C1]"


def test_a_generation_with_no_claims_is_retried():
    """The model can answer "[C1]": a valid citation with no sentence attached.
    Citation validation has nothing to strip and the guard has nothing to
    verify, so without this the one allowed regeneration was never spent."""
    cfg = GuardConfig(enabled=True, max_regenerations=1)
    assert should_regenerate([], cfg, attempts=1) is True
    assert should_regenerate([], cfg, attempts=2) is False  # budget respected
    assert "chỉ gồm mã trích dẫn" in regeneration_feedback([])


def test_a_fully_supported_answer_is_not_retried():
    claims = [Claim(text="Ít nhất 85%.", citations=["C1"], verdict=Verdict.SUPPORTED)]
    assert should_regenerate(claims, GuardConfig(enabled=True), attempts=1) is False


class ByPremise:
    """Supports a claim only against the premise that contains `needle`."""

    def __init__(self, needle):
        self.needle = needle

    def entailment(self, premise, hypothesis):
        return 0.95 if self.needle in premise else 0.05


def _two_sources():
    return [
        RetrievedChunk(chunk=Chunk(chunk_id="a", doc_id="d", text="Khoản 3: điều khác."),
                       score=0.9, label="C1"),
        RetrievedChunk(chunk=Chunk(chunk_id="b", doc_id="d", text="Khoản 2: bằng 75%."),
                       score=0.8, label="C2"),
    ]


def test_a_true_claim_cited_to_the_wrong_source_is_relabelled_not_dropped():
    sources = _two_sources()
    claims = verify_claims("Trợ cấp bằng 75% [C1].", sources, ByPremise("75%"), 0.6)
    assert claims[0].verdict is Verdict.SUPPORTED
    assert claims[0].citations == ["C2"] and claims[0].cited_as == ["C1"]
    out = apply_policy(claims, sources, GuardConfig(enabled=True))
    assert out.status is AnswerStatus.ANSWERED and "[C2]" in out.answer


def test_relabelling_never_rescues_a_claim_no_source_supports():
    sources = _two_sources()
    claims = verify_claims("Trợ cấp bằng 90% [C1].", sources, ByPremise("90%"), 0.6)
    assert claims[0].verdict is Verdict.UNSUPPORTED
    assert claims[0].citations == ["C1"] and claims[0].cited_as is None


def test_a_claim_citing_three_sources_is_also_read_against_each_pair():
    seen = []

    class Recorder:
        def entailment(self, premise, hypothesis):
            seen.append(premise)
            return 0.9 if premise == "A\nC" else 0.1

    sources = [
        RetrievedChunk(chunk=Chunk(chunk_id=x, doc_id="d", text=x), score=0.9, label=f"C{i + 1}")
        for i, x in enumerate("ABC")
    ]
    claims = verify_claims("Hai ý [C1][C2][C3].", sources, Recorder(), 0.6)
    assert claims[0].verdict is Verdict.SUPPORTED
    assert seen[0] == "A\nB\nC"
