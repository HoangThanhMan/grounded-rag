"""The query pipeline, top to bottom.

    retrieve (+ corrective loop) -> floor -> generate -> split -> verify -> policy -> answer

Everything else in the package is a component this function calls. Read this
file first; it is the shape of the whole system.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from grounded_rag.config import RunConfig
from grounded_rag.generation.citation import invalid_citations
from grounded_rag.generation.llm_client import MeteredLLM, get_llm_client
from grounded_rag.generation.prompts import SYSTEM_PROMPT, build_user_prompt
from grounded_rag.guard.claim_splitter import split_claims
from grounded_rag.guard.nli_verifier import get_verifier
from grounded_rag.guard.policy import (
    apply_policy,
    is_abstention,
    regeneration_feedback,
    should_regenerate,
    unsupported,
    verify_claims,
)
from grounded_rag.observability import metrics
from grounded_rag.observability.tracing import collect_steps, trace
from grounded_rag.retrieval.corrective import retrieve
from grounded_rag.types import (
    ABSTAIN_TEXT,
    AbstainReason,
    Answer,
    AnswerStatus,
    Claim,
    RetrievedChunk,
)

log = logging.getLogger("grounded_rag.service")


async def answer_question(
    question: str, config: RunConfig, *, as_of: date | None = None
) -> Answer:
    """`as_of` is the day the law is read on: regulations not in force that
    day are never retrieved. Defaults to today."""
    started = time.perf_counter()
    llm = MeteredLLM(get_llm_client(), config.max_llm_calls)

    with collect_steps() as steps:
        out = await _answer(question, config, llm, as_of or date.today())

    out.meta.latency_ms = int((time.perf_counter() - started) * 1000)
    out.meta.tokens = llm.tokens
    out.meta.llm_calls = llm.calls
    out.meta.cost_usd = round(llm.cost_usd, 6)
    out.meta.config = config.name
    out.meta.steps = steps
    metrics.observe_answer(out)
    return out


async def _answer(question: str, config: RunConfig, llm: MeteredLLM, as_of: date) -> Answer:
    retrieval = await retrieve(question, config, llm, as_of)
    if retrieval.out_of_domain:
        return _declined(AnswerStatus.NO_CONTEXT, AbstainReason.OUT_OF_DOMAIN)
    # Floor: nothing retrieved well enough, so do not let the LLM improvise.
    if not retrieval.hits:
        return _declined(AnswerStatus.NO_CONTEXT, AbstainReason.RETRIEVAL_FLOOR)

    sources = [
        RetrievedChunk(chunk=c, score=round(s, 4), label=f"C{i + 1}")
        for i, (c, s) in enumerate(retrieval.hits)
    ]
    user = build_user_prompt(question, sources)

    attempts = 0
    claims: list[Claim] = []
    text = ""

    while True:
        attempts += 1
        with trace("generate", attempt=attempts) as span:
            res = await llm.complete(
                SYSTEM_PROMPT,
                user,
                temperature=config.generation.temperature,
                max_tokens=config.generation.max_tokens,
            )
            span.update(tokens=res.tokens, truncated=res.truncated)
        text = res.text
        # The raw text goes to the log, never into the response: an
        # unverified sentence must not reach the user by a side door.
        log.debug("generation attempt=%d truncated=%s: %r", attempts, res.truncated, text)
        if res.truncated:
            log.warning(
                "generation hit max_tokens=%d - the answer is cut off. Thinking models "
                "spend output tokens on reasoning: raise generation.max_tokens or set "
                "LLM_REASONING_EFFORT.",
                config.generation.max_tokens,
            )

        # A citation to a label we never supplied is a hallucination we can
        # catch for free, before running any model.
        bogus = invalid_citations(text, [s.label for s in sources])
        if bogus:
            text = _drop_bogus(text, bogus)

        # The model declined on its own. After a regeneration, it declined
        # because the guard told it what was unsupported - the guard's credit.
        if is_abstention(text):
            reason = AbstainReason.MODEL if attempts == 1 else AbstainReason.GUARD
            return _declined(AnswerStatus.ABSTAINED, reason, sources, regenerated=attempts > 1)

        if not config.guard.enabled:
            # No verification at all, so the baseline pays nothing for the
            # guard. eval/run.py scores every configuration with the same
            # instrument afterwards - see docs/07-evaluation-plan.md.
            claims = split_claims(text)
            break

        with trace("verify") as span:
            claims = verify_claims(
                text, sources, get_verifier(), config.guard.entailment_threshold
            )
            span.update(claims=len(claims), unsupported=len(unsupported(claims)))

        if not should_regenerate(claims, config.guard, attempts) or llm.left < 1:
            break
        user = f"{build_user_prompt(question, sources)}\n\n{regeneration_feedback(claims)}"

    out = apply_policy(claims, sources, config.guard, regenerated=attempts > 1, raw_text=text)
    if out.status is AnswerStatus.ABSTAINED:
        out.meta.abstain_reason = AbstainReason.GUARD
    return out


def _drop_bogus(text: str, labels: list[str]) -> str:
    for label in labels:
        text = text.replace(f"[{label}]", "")
    return text


def _declined(
    status: AnswerStatus,
    reason: AbstainReason,
    sources: list[RetrievedChunk] | None = None,
    *,
    regenerated: bool = False,
) -> Answer:
    out = Answer(answer=ABSTAIN_TEXT, status=status, sources=sources or [])
    out.meta.abstain_reason = reason
    out.meta.regenerated = regenerated
    return out
