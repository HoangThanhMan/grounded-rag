"""The models run on CPU and take seconds per call. A question waiting on one
must not stop the server answering anything else - /healthz above all, or
an orchestrator restarts a server that is merely busy."""

import asyncio
import time
from pathlib import Path

import pytest

from grounded_rag.ingest.loaders import load_file
from grounded_rag.ingest.pipeline import ingest_file
from grounded_rag.retrieval import search as search_module
from grounded_rag.retrieval.reranker import LexicalReranker
from grounded_rag.service import answer_question

SLOW_S = 0.4
SAMPLE = Path("data/sample_corpus/bo_luat_lao_dong_2019.md")


class SlowReranker:
    """A cross-encoder on CPU: holds the thread it runs on for SLOW_S."""

    def rerank(self, query, candidates, top_n):
        time.sleep(SLOW_S)
        return LexicalReranker().rerank(query, candidates, top_n)


@pytest.mark.asyncio
async def test_the_event_loop_stays_free_while_questions_wait_on_the_models(monkeypatch):
    ingest_file(SAMPLE, "bo_luat_lao_dong_2019", load_file(SAMPLE).meta)
    monkeypatch.setattr(search_module, "get_reranker", lambda: SlowReranker())

    async def probe() -> float:
        await asyncio.sleep(0.05)       # due while the three are in the reranker
        # Measured from when it was due, not from when it got to run: a
        # blocked loop delays the start of this coroutine too.
        return time.perf_counter() - started - 0.05

    started = time.perf_counter()
    waited, *answers = await asyncio.gather(
        probe(), *(answer_question("Thời giờ làm việc?") for _ in range(3))
    )
    assert all(a.sources for a in answers)
    # Blocking the event loop makes this the sum of the three reranker calls.
    assert waited < 0.1, f"the loop was blocked for {waited:.2f}s behind the models"
