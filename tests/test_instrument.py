"""The eval's measuring instrument judges every configuration against
clause-sized premises, so chunk size cannot pass for hallucination."""

from pathlib import Path

from eval.instrument import ClauseIndex, judge_claims
from grounded_rag.ingest.chunkers import recursive_chunk
from grounded_rag.ingest.loaders import load_file
from grounded_rag.types import Answer, AnswerStatus, Chunk, RetrievedChunk, Verdict

SAMPLE = Path("data/sample_corpus")


class ReadsOnlyShortPremises:
    """Stands in for an NLI model that loses the thread on long premises: it
    entails only when the premise is clause-sized and contains the claim's key
    phrase. The real mDeBERTa behaved like this on 600-token windows."""

    def entailment(self, premise: str, hypothesis: str) -> float:
        return 0.95 if len(premise) < 900 and "45 ngày" in premise else 0.1


def test_a_recursive_window_is_judged_through_the_clauses_it_contains():
    index = ClauseIndex(SAMPLE)
    doc = load_file(SAMPLE / "bo_luat_lao_dong_2019.md")
    window = recursive_chunk(doc.text, doc.doc_id, max_chars=2000)[0]
    assert len(window.text) > 900 and window.article is None

    premises = index.premises(window)
    assert premises[0] == window.text
    assert any(p.startswith("Điều 35. Quyền đơn phương") and "45 ngày" in p for p in premises[1:])

    answer = Answer(answer="Phải báo trước ít nhất 45 ngày [C1].", status=AnswerStatus.ANSWERED,
                    sources=[RetrievedChunk(chunk=window, score=0.9, label="C1")])
    judged = judge_claims(answer, ReadsOnlyShortPremises(), 0.6, index)
    assert judged[0].verdict is Verdict.SUPPORTED


class LosesTheThreadInOtherArticles:
    """Entails only a premise holding both clause 1 and clause 2 of Điều 35
    and nothing from other articles - the shape of the real Điều 105 case."""

    def entailment(self, premise: str, hypothesis: str) -> float:
        both = "Ít nhất 45 ngày" in premise and "không cần báo trước" in premise
        return 0.95 if both and "Điều 105" not in premise else 0.1


def test_one_sentence_spanning_two_neighbouring_clauses_of_the_window_is_supported():
    index = ClauseIndex(SAMPLE)
    doc = load_file(SAMPLE / "bo_luat_lao_dong_2019.md")
    window = recursive_chunk(doc.text, doc.doc_id, max_chars=2000)[0]
    assert "Điều 105" in window.text  # the window carries another article too
    claim = "Phải báo trước ít nhất 45 ngày, nhưng không cần báo trước khi bị ngược đãi [C1]."
    answer = Answer(answer=claim, status=AnswerStatus.ANSWERED,
                    sources=[RetrievedChunk(chunk=window, score=0.9, label="C1")])
    judged = judge_claims(answer, LosesTheThreadInOtherArticles(), 0.6, index)
    assert judged[0].verdict is Verdict.SUPPORTED


def test_a_structural_chunk_is_judged_as_cited():
    index = ClauseIndex(SAMPLE)
    chunk = Chunk(chunk_id="x", doc_id="d", text="Điều 1. X\n1. Nội dung.", article="Điều 1",
                  clause="Khoản 1")
    assert index.premises(chunk) == [chunk.text]


def test_abstentions_have_nothing_to_judge():
    answer = Answer(answer="Không tìm thấy thông tin này trong tài liệu.",
                    status=AnswerStatus.NO_CONTEXT)
    assert judge_claims(answer, ReadsOnlyShortPremises(), 0.6, ClauseIndex(SAMPLE)) == []
