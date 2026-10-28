"""Domain types shared across the pipeline."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

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


class Turn(BaseModel):
    """One earlier message of the conversation, for rewriting a follow-up."""

    role: Literal["user", "assistant"]
    content: str


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"         # the LLM was asked and no cited answer came back
    NO_CONTEXT = "no_context"       # stopped before the LLM: nothing relevant retrieved


class AbstainReason(StrEnum):
    """Which check stopped the answer - shown to the user, counted in /metrics."""

    RETRIEVAL_FLOOR = "retrieval_floor"
    MODEL = "model"                     # the model used the refusal sentence itself
    NO_CITATION = "no_citation"         # the answer cited no source it was given
    TRUNCATED = "truncated"             # max_tokens cut the answer off mid-way


ABSTAIN_TEXT = "Không tìm thấy thông tin này trong tài liệu."


class Step(BaseModel):
    """One span of the pipeline, returned with the answer so its cost is visible."""

    name: str                       # condense | retrieve | generate
    ms: int
    detail: dict[str, Any] = Field(default_factory=dict)


class AnswerMeta(BaseModel):
    latency_ms: int = 0
    abstain_reason: AbstainReason | None = None
    steps: list[Step] = Field(default_factory=list)


class Answer(BaseModel):
    answer: str
    status: AnswerStatus
    sources: list[RetrievedChunk] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)   # labels cited, in order
    # what was retrieved for: the question itself, or a follow-up rewritten
    # to stand on its own
    standalone_question: str = ""
    meta: AnswerMeta = Field(default_factory=AnswerMeta)
