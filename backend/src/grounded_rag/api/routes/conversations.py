"""Conversation history and feedback on answers - each browser's own only
(api/owner.py). Someone else's conversation is a 404, not a 403: its
existence is not anyone else's business either."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from grounded_rag.api.errors import AppError
from grounded_rag.api.owner import current_owner
from grounded_rag.api.schemas import (
    ConversationOut,
    ConversationSummary,
    FeedbackIn,
    FeedbackOut,
    MessageOut,
)
from grounded_rag.db.models import Conversation, Feedback, Message, new_id, now
from grounded_rag.db.session import get_session

router = APIRouter(prefix="/api", tags=["conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]
Owner = Annotated[str, Depends(current_owner)]
LIST_LIMIT = 50


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(session: Session, owner: Owner):
    return (
        await session.scalars(
            select(Conversation)
            .where(Conversation.owner_id == owner)
            .order_by(Conversation.updated_at.desc())
            .limit(LIST_LIMIT)
        )
    ).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, session: Session, owner: Owner):
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.owner_id == owner)
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
async def delete_conversation(conversation_id: str, session: Session, owner: Owner) -> Response:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.owner_id != owner:
        raise AppError(404, "not_found", f"no conversation {conversation_id!r}")
    await session.delete(conv)
    await session.commit()
    return Response(status_code=204)


@router.put("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def put_feedback(message_id: str, body: FeedbackIn, session: Session, owner: Owner):
    """👍 / 👎 on an answer. Asking again changes the rating, it does not add one."""
    msg = await session.get(Message, message_id)
    conv = await session.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or msg.role != "assistant" or conv is None or conv.owner_id != owner:
        raise AppError(404, "not_found", f"no answer {message_id!r}")
    # One statement, not select-then-insert: two quick clicks would both find
    # no rating and the second insert would break the unique constraint.
    dialect = postgresql if session.bind.dialect.name == "postgresql" else sqlite
    stmt = dialect.insert(Feedback).values(
        id=new_id(), message_id=message_id, rating=body.rating, comment=body.comment,
        created_at=now(),
    )
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[Feedback.message_id],
        set_={"rating": body.rating, "comment": body.comment},
    ))
    await session.commit()
    return FeedbackOut(message_id=message_id, rating=body.rating, comment=body.comment)
