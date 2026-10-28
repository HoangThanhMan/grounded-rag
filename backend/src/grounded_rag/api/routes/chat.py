"""POST /api/chat - one question, answered as a server-sent event stream.

    meta     {conversation_id, title}            at once
    sources  {standalone_question, sources}      after retrieval
    token    {text}                              while the answer is written
    done     {message_id, answer, status, ...}   the checked answer - the client
                                                 shows this, not the streamed draft
    error    {code, message}                     instead of done

The question is saved before the stream starts; the answer only once it is
done. A stream that fails halfway leaves the question without an answer
rather than a half-written one on record.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grounded_rag.api.errors import AppError
from grounded_rag.api.ratelimit import rate_limit
from grounded_rag.api.schemas import ChatRequest, SourceOut
from grounded_rag.config import settings
from grounded_rag.db.models import Conversation, Message, new_id, now
from grounded_rag.db.session import SessionLocal, get_session
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.service import DoneEvent, SourcesEvent, TokenEvent, answer_stream
from grounded_rag.types import Answer, Turn

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger("grounded_rag.chat")
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/chat", dependencies=[Depends(rate_limit)])
async def chat(req: ChatRequest, session: Session) -> StreamingResponse:
    if req.conversation_id:
        conv = await session.get(Conversation, req.conversation_id)
        if conv is None:
            raise AppError(404, "not_found", f"no conversation {req.conversation_id!r}")
        history = await _history(session, conv.id)
    else:
        conv = Conversation(id=new_id(), title=req.question[:60])
        session.add(conv)
        history = []
    session.add(Message(conversation_id=conv.id, role="user", content=req.question))
    conv.updated_at = now()
    await session.commit()
    conv_id, title = conv.id, conv.title

    async def events():
        yield _sse("meta", {"conversation_id": conv_id, "title": title})
        try:
            async for event in answer_stream(req.question, history=history, as_of=req.as_of):
                if isinstance(event, SourcesEvent):
                    yield _sse("sources", {
                        "standalone_question": event.standalone_question,
                        "sources": [SourceOut.of(s).model_dump(mode="json")
                                    for s in event.sources],
                    })
                elif isinstance(event, TokenEvent):
                    yield _sse("token", {"text": event.text})
                elif isinstance(event, DoneEvent):
                    message_id = await _save_answer(conv_id, event.answer)
                    yield _sse("done", _done(message_id, event.answer))
        except LLMUnavailable as e:
            # headers are already sent, so the 503 travels as an event
            log.warning("LLM unavailable mid-request: %s", e)
            yield _sse("error", {"code": "llm_unavailable",
                                 "message": "the language model is unavailable, try again"})
        except Exception:
            log.exception("chat stream failed")
            yield _sse("error", {"code": "internal", "message": "internal server error"})

    # X-Accel-Buffering: nginx would otherwise hold the tokens back
    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _history(session: AsyncSession, conversation_id: str) -> list[Turn]:
    recent = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(2 * settings.history_turns)
        )
    ).all()
    return [Turn(role=m.role, content=m.content) for m in reversed(recent)]


async def _save_answer(conversation_id: str, answer: Answer) -> str:
    # its own session: the request's may already be closed while the stream runs
    async with SessionLocal() as session:
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer.answer,
            status=str(answer.status),
            abstain_reason=str(answer.meta.abstain_reason) if answer.meta.abstain_reason else None,
            sources=[SourceOut.of(s).model_dump(mode="json") for s in answer.sources],
            citations=answer.citations,
            standalone_question=answer.standalone_question,
            latency_ms=answer.meta.latency_ms,
        )
        session.add(msg)
        conv = await session.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = now()
        await session.commit()
        return msg.id


def _done(message_id: str, answer: Answer) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "answer": answer.answer,
        "status": answer.status,
        "abstain_reason": answer.meta.abstain_reason,
        "citations": answer.citations,
        "latency_ms": answer.meta.latency_ms,
    }


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
