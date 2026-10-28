"""The tables. Ids are random hex strings, times are timezone-aware UTC.

Every column type here exists in both Postgres (docker compose) and SQLite
(tests, running natively), so one migration serves both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # the browser that started it (api/owner.py); conversations from before
    # owners existed have none and belong to nobody
    owner_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))           # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # assistant messages only
    status: Mapped[str | None] = mapped_column(String(16))
    abstain_reason: Mapped[str | None] = mapped_column(String(32))
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    citations: Mapped[list[str] | None] = mapped_column(JSON)
    standalone_question: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback: Mapped[Feedback | None] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[str] = mapped_column(String(8))          # up | down
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    """One law in the library. The id is also the `doc_id` of its chunks."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    number: Mapped[str | None] = mapped_column(String(100))
    issued_by: Mapped[str | None] = mapped_column(String(200))
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(300))      # as uploaded
    path: Mapped[str] = mapped_column(String(500))          # where the file is on disk
    status: Mapped[str] = mapped_column(String(16))         # processing | ready | failed
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
