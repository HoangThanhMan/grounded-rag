"""Conversation history and feedback on answers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from grounded_rag.api.errors import AppError
from grounded_rag.api.schemas import (
    ConversationOut,
    ConversationSummary,
    FeedbackIn,
    FeedbackOut,
    MessageOut,
)
from grounded_rag.db.models import Conversation, Feedback, Message
from grounded_rag.db.session import get_session

router = APIRouter(prefix="/api", tags=["conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]
LIST_LIMIT = 50


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(session: Session):
    return (
        await session.scalars(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(LIST_LIMIT)
        )
    ).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, session: Session):
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages).selectinload(Message.feedback))
    )
    if conv is None:
        raise AppError(404, "not_found", f"no conversation {conversation_id!r}")
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content, status=m.status,
                abstain_reason=m.abstain_reason, sources=m.sources, citations=m.citations,
                feedback=m.feedback.rating if m.feedback else None, created_at=m.created_at,
            )
            for m in conv.messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, session: Session) -> Response:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise AppError(404, "not_found", f"no conversation {conversation_id!r}")
    await session.delete(conv)
    await session.commit()
    return Response(status_code=204)


@router.put("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def put_feedback(message_id: str, body: FeedbackIn, session: Session):
    """👍 / 👎 on an answer. Asking again changes the rating, it does not add one."""
    msg = await session.get(Message, message_id)
    if msg is None or msg.role != "assistant":
        raise AppError(404, "not_found", f"no answer {message_id!r}")
    fb = await session.scalar(select(Feedback).where(Feedback.message_id == message_id))
    if fb is None:
        fb = Feedback(message_id=message_id)
        session.add(fb)
    fb.rating, fb.comment = body.rating, body.comment
    await session.commit()
    return fb
