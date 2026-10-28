"""End to end on the mock provider: no API key, no model weights."""

from datetime import date
from pathlib import Path

import pytest

from grounded_rag import service
from grounded_rag.config import RetrievalOptions
from grounded_rag.generation.llm_client import LLMResponse
from grounded_rag.generation.prompts import CONDENSE_SYSTEM_PROMPT
from grounded_rag.ingest.loaders import load_file
from grounded_rag.ingest.pipeline import ingest_file
from grounded_rag.service import DoneEvent, SourcesEvent, TokenEvent, answer_question, answer_stream
from grounded_rag.types import ABSTAIN_TEXT, AbstainReason, AnswerStatus, Turn

SAMPLE = Path("data/sample_corpus/bo_luat_lao_dong_2019.md")
NOTICE = "Người lao động nghỉ việc phải báo trước bao nhiêu ngày?"
HOURS = "Thời giờ làm việc bình thường tối đa trong một ngày là bao nhiêu giờ?"


@pytest.fixture(scope="module", autouse=True)
def indexed():
    ingest_file(SAMPLE, "bo_luat_lao_dong_2019", load_file(SAMPLE).meta)


class Scripted:
    """An LLM that says what the test tells it to, and remembers being asked."""

    def __init__(self, answer: str, condensed: str = "") -> None:
        self.answer, self.condensed = answer, condensed
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system, user, **kw):
        self.calls.append((system, user))
        return LLMResponse(text=self.condensed)

    async def stream(self, system, user, **kw):
        self.calls.append((system, user))
        for word in self.answer.split(" "):
            yield word + " "


def _use(monkeypatch, llm) -> None:
    monkeypatch.setattr(service, "get_llm_client", lambda: llm)


@pytest.mark.asyncio
async def test_answers_with_a_valid_citation():
    answer = await answer_question(HOURS)
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.citations == ["C1"]
    assert "[C1]" in answer.answer
    assert answer.sources[0].chunk.ref == "bo_luat_lao_dong_2019:Điều 105:1"
    assert [s.name for s in answer.meta.steps] == ["retrieve", "generate"]


@pytest.mark.asyncio
async def test_stream_emits_sources_then_tokens_then_done():
    kinds = [type(e) async for e in answer_stream(NOTICE)]
    assert kinds[0] is SourcesEvent
    assert kinds[-1] is DoneEvent
    assert set(kinds[1:-1]) == {TokenEvent}
    assert len(kinds) > 3


@pytest.mark.asyncio
async def test_bogus_citation_is_removed(monkeypatch):
    _use(monkeypatch, Scripted("Phải báo trước ít nhất 45 ngày [C1][C9]."))
    answer = await answer_question(NOTICE)
    assert "[C9]" not in answer.answer
    assert answer.citations == ["C1"]
    assert answer.status is AnswerStatus.ANSWERED


@pytest.mark.asyncio
async def test_answer_without_citation_is_refused(monkeypatch):
    _use(monkeypatch, Scripted("Phải báo trước ít nhất 45 ngày."))
    answer = await answer_question(NOTICE)
    assert answer.status is AnswerStatus.ABSTAINED
    assert answer.meta.abstain_reason is AbstainReason.NO_CITATION
    assert answer.answer == ABSTAIN_TEXT


@pytest.mark.asyncio
async def test_model_refusal_is_abstained(monkeypatch):
    _use(monkeypatch, Scripted(ABSTAIN_TEXT))
    answer = await answer_question(NOTICE)
    assert answer.status is AnswerStatus.ABSTAINED
    assert answer.meta.abstain_reason is AbstainReason.MODEL


@pytest.mark.asyncio
async def test_floor_stops_before_the_llm(monkeypatch):
    llm = Scripted("không được gọi [C1]")
    _use(monkeypatch, llm)
    answer = await answer_question(NOTICE, options=RetrievalOptions(min_score=2.0))
    assert answer.status is AnswerStatus.NO_CONTEXT
    assert answer.meta.abstain_reason is AbstainReason.RETRIEVAL_FLOOR
    assert llm.calls == []


@pytest.mark.asyncio
async def test_as_of_before_any_law_is_no_context():
    answer = await answer_question(NOTICE, as_of=date(2010, 1, 1))
    assert answer.status is AnswerStatus.NO_CONTEXT
    assert answer.sources == []


@pytest.mark.asyncio
async def test_follow_up_is_condensed(monkeypatch):
    llm = Scripted("Ít nhất 45 ngày [C1].", condensed="Thời hạn báo trước khi nghỉ việc")
    _use(monkeypatch, llm)
    history = [Turn(role="user", content=NOTICE), Turn(role="assistant", content="45 ngày [C1].")]
    answer = await answer_question("Còn hợp đồng có thời hạn thì sao?", history=history)
    assert answer.standalone_question == "Thời hạn báo trước khi nghỉ việc"
    assert llm.calls[0][0] == CONDENSE_SYSTEM_PROMPT
    assert NOTICE in llm.calls[0][1]


@pytest.mark.asyncio
async def test_first_question_is_not_condensed(monkeypatch):
    llm = Scripted("Ít nhất 45 ngày [C1].")
    _use(monkeypatch, llm)
    answer = await answer_question(NOTICE)
    assert answer.standalone_question == NOTICE
    assert len(llm.calls) == 1


def test_today_is_the_day_in_vietnam():
    from datetime import UTC, datetime

    from grounded_rag.service import law_today

    # 23:30 UTC on the 27th is 06:30 on the 28th in Hà Nội
    assert law_today(datetime(2026, 10, 27, 23, 30, tzinfo=UTC)) == date(2026, 10, 28)


@pytest.mark.asyncio
async def test_an_answer_cut_off_at_max_tokens_is_refused(monkeypatch):
    """A legal answer cut mid-sentence can drop the condition that matters."""

    class CutOff:
        finish_reason = "length"

        def __init__(self):
            self._words = iter(["Phải ", "báo ", "trước [C1] ", "trừ khi"])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._words)
            except StopIteration:
                raise StopAsyncIteration from None

    class Llm:
        async def complete(self, *a, **kw):
            return LLMResponse(text="")

        def stream(self, *a, **kw):
            return CutOff()

    _use(monkeypatch, Llm())
    answer = await answer_question(NOTICE)
    assert answer.status is AnswerStatus.ABSTAINED
    assert answer.meta.abstain_reason == "truncated"
