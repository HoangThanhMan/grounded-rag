import pytest

from grounded_rag.observability import tracing
from grounded_rag.types import (
    Answer,
    AnswerStatus,
    Chunk,
    Claim,
    RetrievedChunk,
    Verdict,
)


class FakeTrace:
    id = "t-1"

    def __init__(self, **kw):
        self.kw, self.spans, self.generations, self.scores = kw, [], [], []

    def span(self, **kw):
        self.spans.append(kw)

    def generation(self, **kw):
        self.generations.append(kw)

    def score(self, **kw):
        self.scores.append(kw)


class FakeLangfuse:
    def __init__(self):
        self.traces = []

    def trace(self, **kw):
        self.traces.append(FakeTrace(**kw))
        return self.traces[-1]


def _answer():
    with tracing.collect_steps() as steps:
        with tracing.trace("retrieve", top_score=0.9):
            pass
        with tracing.trace("generate", attempt=1) as span:
            span.update(tokens=120)
        with tracing.trace("verify"):
            pass
    chunk = Chunk(chunk_id="c", doc_id="d", text="Không quá 08 giờ.", article="Điều 105")
    out = Answer(
        answer="Không quá 08 giờ [C1].",
        status=AnswerStatus.ANSWERED,
        claims=[Claim(text="Không quá 08 giờ.", citations=["C1"], entailment=0.97,
                      verdict=Verdict.SUPPORTED)],
        sources=[RetrievedChunk(chunk=chunk, score=0.9, label="C1")],
    )
    out.meta.steps, out.meta.config = steps, "full"
    return out


def test_an_answer_becomes_one_trace_with_a_span_per_step_and_guard_scores():
    client = FakeLangfuse()
    assert tracing.export("Bao nhiêu giờ?", _answer(), client) == "t-1"
    (t,) = client.traces
    assert t.kw["input"] == {"question": "Bao nhiêu giờ?"}
    assert t.kw["metadata"]["sources"] == ["d:Điều 105"]
    assert [s["name"] for s in t.spans] == ["retrieve", "verify"]
    assert t.generations[0]["usage"] == {"total": 120}
    assert t.spans[0]["start_time"] <= t.generations[0]["start_time"]
    assert {s["name"] for s in t.scores} == {"claims_supported", "entailment"}


def test_a_failing_export_never_fails_the_answer():
    class Broken:
        def trace(self, **kw):
            raise ConnectionError("langfuse down")

    assert tracing.export("q", _answer(), Broken()) is None


def test_start_times_stay_out_of_the_api_response():
    assert "started" not in _answer().meta.steps[0].model_dump()


@pytest.fixture(autouse=True)
def no_real_client(monkeypatch):
    monkeypatch.setattr(tracing, "_client", False)
