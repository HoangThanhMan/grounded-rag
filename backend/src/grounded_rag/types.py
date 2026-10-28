"""Domain types shared across the pipeline."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class DocMeta(BaseModel):
    """Document-level metadata, from YAML front matter (see ingest/loaders.py)."""

    title: str | None = None            # "Bộ luật Lao động 2019"
    number: str | None = None           # "45/2019/QH14"
    issued_by: str | None = None        # "Quốc hội"
    effective_date: date | None = None
    expiry_date: date | None = None     # None = still in force


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    article: str | None = None      # "Điều 35"
    clause: str | None = None       # "Khoản 1"
    chapter: str | None = None      # "Chương III"
    doc_title: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    page: int | None = None
    lang: str = "vi"

    @computed_field
    @property
    def ref(self) -> str:
        """Human-readable address, the format gold_chunks are written in:
        "bo_luat_lao_dong_2019:Điều 35:1". Falls back to chunk_id for chunks
        that carry no legal structure."""
        if not self.article:
            return self.chunk_id
        if self.clause:
            return f"{self.doc_id}:{self.article}:{self.clause.removeprefix('Khoản ').strip()}"
        return f"{self.doc_id}:{self.article}"

    def in_force(self, on: date) -> bool:
        """A regulation that has not started or has already expired must not be
        retrieved - in law, an outdated clause is a wrong answer, not an old one."""
        if self.effective_date and self.effective_date > on:
            return False
        return not (self.expiry_date and self.expiry_date <= on)


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    label: str                      # "C1", "C2", ... - what the LLM cites


class Verdict(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCITED = "uncited"             # the model made a claim with no citation at all


class Claim(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)
    entailment: float | None = None
    verdict: Verdict | None = None  # None = not verified (guard disabled)
    # set when the guard moved the citation to the source that does support
    # the claim: what the model originally cited
    cited_as: list[str] | None = None


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"             # some claims dropped by the guard
    ABSTAINED = "abstained"         # the model or the guard declined to answer
    NO_CONTEXT = "no_context"       # stopped before the LLM ever wrote an answer


class AbstainReason(StrEnum):
    """Which layer of defence stopped the answer - reported per layer in eval."""

    RETRIEVAL_FLOOR = "retrieval_floor"
    OUT_OF_DOMAIN = "out_of_domain"     # the query planner saw no legal question
    MODEL = "model"                     # the model used the refusal sentence itself
    GUARD = "guard"                     # the guard rejected every claim


ABSTAIN_TEXT = "Không tìm thấy thông tin này trong tài liệu."


class Step(BaseModel):
    """One span of the pipeline, returned with the answer so its cost is visible."""

    name: str                       # retrieve | plan | generate | verify
    ms: int
    detail: dict[str, Any] = Field(default_factory=dict)
    # wall-clock start, for exporting the span to Langfuse; not part of the API
    started: datetime | None = Field(default=None, exclude=True)


class AnswerMeta(BaseModel):
    regenerated: bool = False
    latency_ms: int = 0
    tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0
    config: str = "unnamed"
    abstain_reason: AbstainReason | None = None
    steps: list[Step] = Field(default_factory=list)


class Answer(BaseModel):
    answer: str
    status: AnswerStatus
    claims: list[Claim] = Field(default_factory=list)
    sources: list[RetrievedChunk] = Field(default_factory=list)
    meta: AnswerMeta = Field(default_factory=AnswerMeta)
