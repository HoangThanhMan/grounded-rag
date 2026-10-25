"""The models run on CPU and take seconds per call. A request waiting on one
must not stop the server answering anything else - /healthz above all, or
an orchestrator restarts a server that is merely busy."""

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from grounded_rag.api.main import app
from grounded_rag.config import RunConfig
from grounded_rag.ingest.pipeline import ingest
from grounded_rag.retrieval import corrective
from grounded_rag.retrieval.reranker import LexicalReranker

SLOW_S = 0.4


class SlowReranker:
    """A cross-encoder on CPU: holds the thread it runs on for SLOW_S."""

    def rerank(self, query, candidates, top_n):
        time.sleep(SLOW_S)
        return LexicalReranker().rerank(query, candidates, top_n)


@pytest.mark.asyncio
async def test_healthz_answers_while_chat_requests_wait_on_the_models(monkeypatch):
    ingest(Path("data/sample_corpus"), RunConfig.from_yaml("configs/full.yaml"))
    monkeypatch.setattr(corrective, "get_reranker", lambda: SlowReranker())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def probe() -> tuple[httpx.Response, float]:
            await asyncio.sleep(0.05)       # sent while the three are in the reranker
            r = await client.get("/healthz")
            # Measured from when it was due, not from when it got to run: a
            # blocked loop delays the start of this coroutine too.
            return r, time.perf_counter() - started - 0.05

        started = time.perf_counter()
        chats = [
            client.post("/chat", json={"question": "Thời giờ làm việc?", "config": "full"})
            for _ in range(3)
        ]
        (health, waited), *answers = await asyncio.gather(probe(), *chats)

    assert health.status_code == 200
    assert all(a.status_code == 200 for a in answers)
    # /healthz should answer in 50 ms under load; doubled so CI noise is not a failure.
    # Blocking the event loop makes this the sum of the three reranker calls.
    assert waited < 0.1, f"/healthz waited {waited:.2f}s behind the models"
