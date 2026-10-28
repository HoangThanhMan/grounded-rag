from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from grounded_rag.api.schemas import ChatRequest, ChatResponse
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.service import answer_question

router = APIRouter(tags=["chat"])
CONFIG_DIR = Path("configs")


def load_config(name: str) -> RunConfig:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, f"unknown config: {name}")
    return RunConfig.from_yaml(path)


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    return await answer_question(req.question, load_config(req.config), as_of=req.as_of)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE.

    Note the ordering: the answer is verified BEFORE the first token goes
    out. Streaming an unverified answer and retracting it afterwards is
    worse than a short wait.
    """
    config = load_config(req.config)

    async def events():
        try:
            answer = await answer_question(req.question, config, as_of=req.as_of)
        except LLMUnavailable as e:
            # headers are already sent, so the 503 travels as an event
            yield f"event: error\ndata: {json.dumps({'detail': str(e)}, ensure_ascii=False)}\n\n"
            return
        for claim in answer.claims:
            yield f"event: claim\ndata: {claim.model_dump_json()}\n\n"
        payload = json.dumps(
            {
                "status": answer.status,
                "answer": answer.answer,
                "meta": answer.meta.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        yield f"event: done\ndata: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
