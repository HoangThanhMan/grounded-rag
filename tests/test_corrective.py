import pytest

from grounded_rag.config import CorrectiveConfig, RunConfig
from grounded_rag.generation.llm_client import LLMResponse, MeteredLLM
from grounded_rag.retrieval import corrective
from grounded_rag.retrieval.corrective import merge, parse_plan, retrieve
from grounded_rag.types import Chunk


def _c(i: int) -> Chunk:
    return Chunk(chunk_id=f"d:{i}", doc_id="d", text=f"đoạn {i}")


class Scripted:
    """A planner that always says the same thing."""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, system, user, **kw):
        return LLMResponse(text=self.reply, tokens=10)


@pytest.fixture
def results(monkeypatch):
    """search() returns whatever a test puts in this table for that query."""
    table: dict = {}
    monkeypatch.setattr(corrective, "search", lambda q, config, as_of: table.get(q, []))
    return table


def _config(**kw) -> RunConfig:
    return RunConfig(corrective=CorrectiveConfig(enabled=True, **kw))


def test_plan_is_read_from_json_wrapped_in_prose():
    plan = parse_plan('Kế hoạch:\n```json\n{"in_domain": true, "queries": ["a", "b"]}\n```', 3)
    assert plan.in_domain and plan.queries == ["a", "b"]


def test_a_garbled_plan_degrades_to_no_new_queries():
    plan = parse_plan("xin lỗi, tôi không hiểu yêu cầu", 3)
    assert plan.in_domain and plan.queries == []


def test_plan_is_capped_at_max_queries():
    assert parse_plan('{"queries": ["a", "b", "c", "d"]}', 2).queries == ["a", "b"]


def test_merge_gives_every_sub_query_a_seat():
    a = [(_c(1), 0.9), (_c(2), 0.8), (_c(3), 0.7)]
    b = [(_c(4), 0.6), (_c(5), 0.5)]
    assert [c.chunk_id for c, _ in merge([a, b], 3, 0.0)] == ["d:1", "d:4", "d:2"]


def test_merge_dedupes_keeps_the_best_score_and_applies_the_floor():
    a = [(_c(1), 0.4), (_c(2), 0.2)]
    b = [(_c(1), 0.9)]
    assert [(c.chunk_id, s) for c, s in merge([a, b], 5, 0.3)] == [("d:1", 0.9)]


@pytest.mark.asyncio
async def test_confident_first_retrieval_costs_no_llm_call(results):
    results["q"] = [(_c(1), 0.9)]
    llm = MeteredLLM(Scripted('{"queries": ["x"]}'), 4)
    out = await retrieve("q", _config(), llm, None)
    assert llm.calls == 0
    assert [c.chunk_id for c, _ in out.hits] == ["d:1"]


@pytest.mark.asyncio
async def test_weak_retrieval_is_rewritten_and_merged(results):
    results["q"] = [(_c(1), 0.2)]
    results["x"] = [(_c(2), 0.8)]
    llm = MeteredLLM(Scripted('{"in_domain": true, "queries": ["x"]}'), 4)
    out = await retrieve("q", _config(), llm, None)
    assert llm.calls == 1
    assert {c.chunk_id for c, _ in out.hits} == {"d:1", "d:2"}


@pytest.mark.asyncio
async def test_the_loop_is_bounded_even_if_nothing_ever_improves(results):
    class Endless:  # proposes a brand-new query every time, none of which retrieves anything
        n = 0

        async def complete(self, system, user, **kw):
            self.n += 1
            return LLMResponse(text=f'{{"queries": ["q{self.n}"]}}')

    llm = MeteredLLM(Endless(), 10)
    await retrieve("q", _config(max_rounds=3), llm, None)
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_a_planner_that_echoes_the_question_ends_the_loop(results, monkeypatch):
    searched = []
    monkeypatch.setattr(corrective, "search", lambda q, config, as_of: searched.append(q) or [])
    llm = MeteredLLM(Scripted('{"queries": ["Nghỉ việc phải báo trước bao lâu"]}'), 4)
    await retrieve("Nghỉ việc phải báo trước bao lâu?", _config(max_rounds=3), llm, None)
    assert (llm.calls, len(searched)) == (1, 1)


@pytest.mark.asyncio
async def test_the_planner_never_spends_the_call_the_answer_needs(results):
    llm = MeteredLLM(Scripted('{"queries": ["x"]}'), 1)
    await retrieve("q", _config(), llm, None)
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_out_of_domain_question_stops_before_generation(results):
    llm = MeteredLLM(Scripted('{"in_domain": false, "queries": []}'), 4)
    out = await retrieve("xin chào", _config(), llm, None)
    assert out.out_of_domain and out.hits == []


@pytest.mark.asyncio
async def test_disabled_loop_never_plans(results):
    llm = MeteredLLM(Scripted('{"queries": ["x"]}'), 4)
    await retrieve("q", RunConfig(), llm, None)
    assert llm.calls == 0
