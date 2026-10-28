"""Request and response bodies of the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from grounded_rag.types import RetrievedChunk


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    number: str | None
    issued_by: str | None
    effective_date: date | None
    expiry_date: date | None
    filename: str
    status: str
    chunks: int
    error: str | None
    updated_at: datetime


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ChatRequest(BaseModel):
    question: Question
    conversation_id: str | None = None      # none = start a new conversation
    as_of: date | None = None               # read the law as of this day; default today


class SourceOut(BaseModel):
    """A retrieved clause as the client shows it next to the answer."""

    label: str                  # what the answer cites: "C1"
    score: float
    ref: str                    # "bo_luat_lao_dong_2019:Điều 35:1"
    doc_id: str
    doc_title: str | None
    article: str | None
    clause: str | None
    text: str
    effective_date: date | None
    expiry_date: date | None

    @classmethod
    def of(cls, s: RetrievedChunk) -> SourceOut:
        c = s.chunk
        return cls(
            label=s.label, score=s.score, ref=c.ref, doc_id=c.doc_id, doc_title=c.doc_title,
            article=c.article, clause=c.clause, text=c.text,
            effective_date=c.effective_date, expiry_date=c.expiry_date,
        )


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    status: str | None
    abstain_reason: str | None
    sources: list[SourceOut] | None
    citations: list[str] | None
    feedback: str | None            # "up" | "down" | None
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    messages: list[MessageOut]


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: Annotated[str, StringConstraints(max_length=1000)] | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    rating: str
    comment: str | None
