"""The query pipeline, top to bottom.

    [follow-up? rewrite it] -> retrieve -> floor -> stream the answer -> check citations
        -> [failed? the stronger model answers once more -> check citations]

Everything else in the package is a component this function calls. Read this
file first; it is the shape of the whole system.

The answer streams to the user as it is written, and the citation check runs
on the finished text. An answer whose citations all point at labels the model
was never given - or that cites nothing - is replaced by the refusal in the
final `done` event: the client shows that, not the streamed draft.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from grounded_rag.compute import run_model
from grounded_rag.config import RetrievalOptions, retrieval_options, settings
from grounded_rag.generation.citation import finalize
from grounded_rag.generation.llm_client import (
    LLMClient,
    LLMUnavailable,
    get_escalation_client,
    get_llm_client,
)
from grounded_rag.generation.prompts import (
    CONDENSE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_condense_prompt,
    build_user_prompt,
)
from grounded_rag.observability import metrics
from grounded_rag.observability.tracing import collect_steps, trace
from grounded_rag.retrieval.search import search
from grounded_rag.types import (
    ABSTAIN_TEXT,
    AbstainReason,
    Answer,
    AnswerStatus,
    RetrievedChunk,
    Turn,
)

log = logging.getLogger("grounded_rag.service")


@dataclass
class SourcesEvent:
    sources: list[RetrievedChunk]
    standalone_question: str


@dataclass
class TokenEvent:
    text: str


@dataclass
class RetryEvent:
    """The draft streamed so far failed the checks; a stronger model starts over."""

    reason: AbstainReason | None


@dataclass
class DoneEvent:
    answer: Answer


Event = SourcesEvent | TokenEvent | RetryEvent | DoneEvent


async def answer_stream(
    question: str,
    *,
    history: Sequence[Turn] = (),
    as_of: date | None = None,
    options: RetrievalOptions | None = None,
) -> AsyncIterator[Event]:
    """`as_of` is the day the law is read on: regulations not in force that
    day are never retrieved. Defaults to today."""
    started = time.perf_counter()
    options = options or retrieval_options()
    llm = get_llm_client()

    with collect_steps() as steps:
        standalone = question
        if history:
            with trace("condense"):
                recent = list(history)[-2 * settings.history_turns :]
                res = await llm.complete(
                    CONDENSE_SYSTEM_PROMPT,
                    build_condense_prompt(recent, question),
                    temperature=0.0,
                    max_tokens=200,
                )
                # an empty rewrite is no reason to lose the question
                standalone = res.text.strip() or question

        with trace("retrieve") as span:
            hits = await run_model(search, standalone, options, as_of or law_today())
            span["hits"] = len(hits)
        sources = [
            RetrievedChunk(chunk=c, score=round(s, 4), label=f"C{i + 1}")
            for i, (c, s) in enumerate(hits)
        ]
        yield SourcesEvent(sources=sources, standalone_question=standalone)

        if not sources:
            # Floor: nothing retrieved well enough, so do not let the LLM improvise.
            answer = _declined(AnswerStatus.NO_CONTEXT, AbstainReason.RETRIEVAL_FLOOR)
        else:
            prompt = build_user_prompt(standalone, sources)
            drafts: list[Answer] = []
            with trace("generate"):
                async for event in _write(llm, prompt, sources, drafts):
                    yield event
            answer = drafts[-1]
            stronger = get_escalation_client()
            if answer.status is AnswerStatus.ABSTAINED and stronger is not None:
                # The sources cleared the floor, yet the answer did not pass:
                # often the cheap model, not the law. One more try, the same prompt.
                yield RetryEvent(reason=answer.meta.abstain_reason)
                try:
                    with trace("escalate"):
                        async for event in _write(stronger, prompt, sources, drafts):
                            yield event
                    answer = drafts[-1]
                    answer.meta.escalated = True
                except LLMUnavailable as e:
                    log.warning("the stronger model is unavailable, keeping the refusal: %s", e)
        answer.sources = sources
        answer.standalone_question = standalone

    answer.meta.steps = steps
    answer.meta.latency_ms = int((time.perf_counter() - started) * 1000)
    metrics.observe_answer(answer)
    yield DoneEvent(answer=answer)


async def answer_question(
    question: str,
    *,
    history: Sequence[Turn] = (),
    as_of: date | None = None,
    options: RetrievalOptions | None = None,
) -> Answer:
    """The same pipeline without the stream, for the evaluation and tests."""
    async for event in answer_stream(question, history=history, as_of=as_of, options=options):
        if isinstance(event, DoneEvent):
            return event.answer
    raise RuntimeError("the answer stream ended without a done event")


def law_today(now: datetime | None = None) -> date:
    tz = ZoneInfo(settings.law_timezone)
    return (now.astimezone(tz) if now else datetime.now(tz)).date()


async def _write(
    llm: LLMClient, prompt: str, sources: list[RetrievedChunk], out: list[Answer]
) -> AsyncIterator[TokenEvent]:
    """One model's answer, streamed as it is written; the checked result is
    appended to `out` once the stream ends."""
    parts: list[str] = []
    stream = llm.stream(
        SYSTEM_PROMPT, prompt, temperature=settings.temperature, max_tokens=settings.max_tokens
    )
    async for token in stream:
        parts.append(token)
        yield TokenEvent(text=token)
    if getattr(stream, "finish_reason", None) == "length":
        # cut mid-sentence: the part missing may be the condition that matters
        answer = _declined(AnswerStatus.ABSTAINED, AbstainReason.TRUNCATED)
    else:
        answer = _checked("".join(parts), sources)
    first = getattr(llm, "model", "")
    answer.meta.model = getattr(stream, "model", "") or first
    answer.meta.fallback = answer.meta.model != first
    out.append(answer)


def _checked(raw: str, sources: list[RetrievedChunk]) -> Answer:
    text, cited = finalize(raw, [s.label for s in sources])
    if text.startswith(ABSTAIN_TEXT.rstrip(".")):
        return _declined(AnswerStatus.ABSTAINED, AbstainReason.MODEL)
    if not cited:
        # Nothing in the answer is tied to a source the user can check.
        log.info("answer cited no supplied source, refused: %r", raw[:200])
        return _declined(AnswerStatus.ABSTAINED, AbstainReason.NO_CITATION)
    return Answer(answer=text, status=AnswerStatus.ANSWERED, citations=cited)


def _declined(status: AnswerStatus, reason: AbstainReason) -> Answer:
    out = Answer(answer=ABSTAIN_TEXT, status=status)
    out.meta.abstain_reason = reason
    return out
