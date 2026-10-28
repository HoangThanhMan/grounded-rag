"""End to end on the mock provider: no API key, no model weights."""

from pathlib import Path

import pytest

from grounded_rag import service
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import LLMResponse
from grounded_rag.ingest.pipeline import ingest
from grounded_rag.service import answer_question
from grounded_rag.types import ABSTAIN_TEXT, AbstainReason, AnswerStatus

SAMPLE = Path("data/sample_corpus")
HOURS = "Thời giờ làm việc bình thường tối đa trong một ngày là bao nhiêu giờ?"


def _config(name: str) -> RunConfig:
    return RunConfig.from_yaml(f"configs/{name}.yaml")


@pytest.fixture(scope="module", autouse=True)
def indexed():
    for name in ("baseline", "full"):  # one index per chunker
        ingest(SAMPLE, _config(name))


@pytest.mark.asyncio
async def test_answers_with_a_verified_citation():
    answer = await answer_question(HOURS, _config("full"))
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.sources[0].chunk.ref == "bo_luat_lao_dong_2019:Điều 105:1"
    assert answer.claims[0].verdict == "supported"
    assert [s.name for s in answer.meta.steps] == ["retrieve", "generate", "verify"]


@pytest.mark.asyncio
async def test_out_of_scope_question_never_reaches_the_llm():
    q = "Mức đóng bảo hiểm y tế của hộ gia đình năm 2026 là bao nhiêu phần trăm?"
    answer = await answer_question(q, _config("full"))
    assert answer.status is AnswerStatus.NO_CONTEXT
    assert answer.meta.abstain_reason is AbstainReason.RETRIEVAL_FLOOR
    assert answer.meta.llm_calls == 0


@pytest.mark.asyncio
async def test_the_models_own_refusal_is_an_abstention_not_a_hallucination(monkeypatch):
    class Refuses:
        async def complete(self, system, user, **kw):
            return LLMResponse(text=ABSTAIN_TEXT, tokens=5)

    monkeypatch.setattr(service, "get_llm_client", lambda: Refuses())
    for name in ("baseline", "full"):
        answer = await answer_question(HOURS, _config(name))
        assert answer.status is AnswerStatus.ABSTAINED
        assert answer.meta.abstain_reason is AbstainReason.MODEL
        assert answer.meta.llm_calls == 1  # no regeneration wasted on a refusal


@pytest.mark.asyncio
async def test_a_cut_off_generation_is_visible_in_the_trace(monkeypatch):
    class CutOff:
        async def complete(self, system, user, **kw):
            return LLMResponse(text="Thời giờ làm việc bình thường không quá", truncated=True)

    monkeypatch.setattr(service, "get_llm_client", lambda: CutOff())
    answer = await answer_question(HOURS, _config("full"))
    generations = [s for s in answer.meta.steps if s.name == "generate"]
    assert generations and all(s.detail["truncated"] for s in generations)


@pytest.mark.asyncio
async def test_baseline_reports_claims_without_verifying_them():
    answer = await answer_question(HOURS, _config("baseline"))
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.claims and all(c.verdict is None for c in answer.claims)
    assert "verify" not in [s.name for s in answer.meta.steps]


@pytest.mark.asyncio
async def test_agentic_config_splits_a_two_part_question():
    q = "Nghỉ việc thì phải báo trước bao nhiêu ngày và mỗi năm được nghỉ phép bao nhiêu ngày?"
    answer = await answer_question(q, _config("agentic"))
    refs = {s.chunk.ref for s in answer.sources}
    assert {"bo_luat_lao_dong_2019:Điều 35:1", "bo_luat_lao_dong_2019:Điều 113:1"} <= refs
    assert "plan" in [s.name for s in answer.meta.steps]
    assert answer.meta.llm_calls <= _config("agentic").max_llm_calls


class Scripted:
    """Answers with each text in turn."""

    def __init__(self, *texts):
        self.texts = list(texts)

    async def complete(self, system, user, **kw):
        return LLMResponse(text=self.texts.pop(0), tokens=5)


GOOD = "Thời giờ làm việc bình thường không quá 08 giờ trong 01 ngày [C1]."
BAD = "Thưởng Tết bằng hai tháng lương [C1]."


@pytest.mark.asyncio
async def test_giving_up_on_regeneration_keeps_the_claims_already_verified(monkeypatch):
    monkeypatch.setattr(service, "get_llm_client", lambda: Scripted(f"{GOOD} {BAD}", ABSTAIN_TEXT))
    answer = await answer_question(HOURS, _config("full"))
    assert answer.status is AnswerStatus.PARTIAL
    assert "08 giờ" in answer.answer and "Tết" not in answer.answer
    assert answer.meta.regenerated and answer.meta.llm_calls == 2


@pytest.mark.asyncio
async def test_a_refusal_after_regeneration_still_shows_what_the_guard_rejected(monkeypatch):
    monkeypatch.setattr(service, "get_llm_client", lambda: Scripted(BAD, ABSTAIN_TEXT))
    answer = await answer_question(HOURS, _config("full"))
    assert answer.status is AnswerStatus.ABSTAINED
    assert answer.meta.abstain_reason is AbstainReason.GUARD
    assert [c.verdict for c in answer.claims] == ["unsupported"]
