"""The HTTP API end to end on the mock provider: the chat stream, the
conversation history it leaves behind, feedback, and the error shape."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grounded_rag import service
from grounded_rag.api.main import app
from grounded_rag.api.routes import health
from grounded_rag.generation.llm_client import LLMResponse, LLMUnavailable
from grounded_rag.ingest.loaders import load_file
from grounded_rag.ingest.pipeline import ingest_file

SAMPLE = Path("data/sample_corpus/bo_luat_lao_dong_2019.md")
HOURS = "Thời giờ làm việc bình thường tối đa trong một ngày là bao nhiêu giờ?"

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def indexed():
    ingest_file(SAMPLE, "bo_luat_lao_dong_2019", load_file(SAMPLE).meta)


def _events(r) -> list[tuple[str, dict]]:
    out = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _chat(**body) -> list[tuple[str, dict]]:
    r = client.post("/api/chat", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return _events(r)


class Scripted:
    def __init__(self, tokens=("Tám giờ ", "[C1]."), condensed="", fail_after=None):
        self.tokens, self.condensed, self.fail_after = tokens, condensed, fail_after
        self.prompts: list[str] = []

    async def complete(self, system, user, **kw):
        self.prompts.append(user)
        return LLMResponse(text=self.condensed)

    async def stream(self, system, user, **kw):
        self.prompts.append(user)
        for i, t in enumerate(self.tokens):
            if self.fail_after is not None and i == self.fail_after:
                raise LLMUnavailable("connection reset")
            yield t
        if self.fail_after is not None and self.fail_after >= len(self.tokens):
            raise LLMUnavailable("connection reset")


def test_chat_streams_meta_sources_tokens_done_and_saves_two_messages():
    events = _chat(question=HOURS)
    kinds = [k for k, _ in events]
    assert kinds[:2] == ["meta", "sources"]
    assert kinds[-1] == "done"
    assert set(kinds[2:-1]) == {"token"}

    meta, sources, done = events[0][1], events[1][1], events[-1][1]
    assert meta["title"] == HOURS[:60]
    src = sources["sources"][0]
    assert src["label"] == "C1"
    assert src["ref"] == "bo_luat_lao_dong_2019:Điều 105:1"
    assert {"doc_id", "doc_title", "article", "clause", "text", "effective_date",
            "expiry_date", "score"} <= src.keys()
    assert done["status"] == "answered"
    assert done["citations"] == ["C1"]

    conv = client.get(f"/api/conversations/{meta['conversation_id']}").json()
    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant"]
    assistant = conv["messages"][1]
    assert assistant["id"] == done["message_id"]
    assert assistant["content"] == done["answer"]
    assert assistant["sources"][0]["ref"] == src["ref"]


def test_follow_up_uses_the_conversation_history(monkeypatch):
    first = _chat(question=HOURS)
    conv_id = first[0][1]["conversation_id"]
    rewritten = "Thời giờ làm việc theo tuần tối đa bao nhiêu giờ?"
    llm = Scripted(condensed=rewritten)
    monkeypatch.setattr(service, "get_llm_client", lambda: llm)
    events = _chat(question="Còn theo tuần thì sao?", conversation_id=conv_id)
    assert HOURS in llm.prompts[0]          # the rewrite saw the first question
    assert events[1][1]["standalone_question"] == rewritten
    conv = client.get(f"/api/conversations/{conv_id}").json()
    assert len(conv["messages"]) == 4


def test_unknown_conversation_is_404():
    r = client.post("/api/chat", json={"question": HOURS, "conversation_id": "khong-co"})
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"] == r.headers["x-request-id"]


def test_blank_question_is_422():
    r = client.post("/api/chat", json={"question": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_overlong_question_is_422():
    assert client.post("/api/chat", json={"question": "a" * 1001}).status_code == 422


def test_provider_down_before_stream_is_error_event(monkeypatch):
    monkeypatch.setattr(service, "get_llm_client", lambda: Scripted(fail_after=0))
    events = _chat(question=HOURS)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "llm_unavailable"


def test_stream_failure_mid_answer_sends_error_and_saves_nothing(monkeypatch):
    monkeypatch.setattr(service, "get_llm_client",
                        lambda: Scripted(tokens=("Người ",), fail_after=1))
    events = _chat(question=HOURS)
    kinds = [k for k, _ in events]
    assert "token" in kinds
    assert kinds[-1] == "error"
    assert "done" not in kinds
    conv = client.get(f"/api/conversations/{events[0][1]['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user"]


def test_feedback_upserts_and_404s_on_user_message():
    events = _chat(question=HOURS)
    message_id = events[-1][1]["message_id"]
    assert client.put(f"/api/messages/{message_id}/feedback",
                      json={"rating": "up"}).status_code == 200
    r = client.put(f"/api/messages/{message_id}/feedback",
                   json={"rating": "down", "comment": "sai điều"})
    assert r.json()["rating"] == "down"
    conv = client.get(f"/api/conversations/{events[0][1]['conversation_id']}").json()
    assert conv["messages"][1]["feedback"] == "down"
    user_msg = conv["messages"][0]["id"]
    assert client.put(f"/api/messages/{user_msg}/feedback",
                      json={"rating": "up"}).status_code == 404
    assert client.put("/api/messages/khong-co/feedback", json={"rating": "up"}).status_code == 404
    assert client.put(f"/api/messages/{message_id}/feedback",
                      json={"rating": "meh"}).status_code == 422


def test_conversations_list_newest_first_and_delete():
    a = _chat(question="Câu hỏi thứ nhất về thời giờ làm việc?")[0][1]["conversation_id"]
    b = _chat(question="Câu hỏi thứ hai về thời giờ làm việc?")[0][1]["conversation_id"]
    ids = [c["id"] for c in client.get("/api/conversations").json()]
    assert ids.index(b) < ids.index(a)
    assert client.delete(f"/api/conversations/{a}").status_code == 204
    assert client.get(f"/api/conversations/{a}").status_code == 404
    assert client.delete(f"/api/conversations/{a}").status_code == 404


def test_request_id_is_echoed_and_generated():
    assert client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers[
        "x-request-id"] == "abc-123"
    generated = client.get("/healthz", headers={"X-Request-ID": "bad id!"}).headers["x-request-id"]
    assert generated != "bad id!" and len(generated) >= 16


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_ok_and_reports_db_failure(monkeypatch):
    assert client.get("/readyz").json() == {"qdrant": "ok", "db": "ok"}

    async def down():
        raise ConnectionError("db is down")

    monkeypatch.setattr(health, "ping_db", down)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"qdrant": "ok", "db": "unavailable"}


def test_unknown_route_has_the_error_shape():
    r = client.get("/api/khong-co")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_a_crash_still_answers_in_the_error_shape_with_the_request_id():
    from fastapi import FastAPI

    from grounded_rag.api import errors
    from grounded_rag.api.middleware import RequestContext

    crashy = FastAPI()
    errors.install(crashy)
    crashy.add_middleware(RequestContext)

    @crashy.get("/boom")
    async def boom():
        raise RuntimeError("secret detail")

    r = TestClient(crashy, raise_server_exceptions=False).get(
        "/boom", headers={"X-Request-ID": "crash-1"})
    assert r.status_code == 500
    assert r.headers["x-request-id"] == "crash-1"
    assert r.json() == {"error": {"code": "internal", "message": "internal server error",
                                  "request_id": "crash-1"}}


def test_conversations_belong_to_the_browser_that_started_them():
    """No accounts, but no shared history either: each browser gets an
    anonymous id in a cookie, and sees only its own conversations."""
    alice, bob = TestClient(app), TestClient(app)
    events = _events(alice.post("/api/chat", json={"question": HOURS}))
    conv, answer = events[0][1]["conversation_id"], events[-1][1]["message_id"]

    assert conv in [c["id"] for c in alice.get("/api/conversations").json()]
    assert conv not in [c["id"] for c in bob.get("/api/conversations").json()]
    assert bob.get(f"/api/conversations/{conv}").status_code == 404
    assert bob.delete(f"/api/conversations/{conv}").status_code == 404
    assert bob.post("/api/chat", json={"question": "Còn gì nữa?",
                                       "conversation_id": conv}).status_code == 404
    assert bob.put(f"/api/messages/{answer}/feedback", json={"rating": "down"}).status_code == 404
    assert alice.get(f"/api/conversations/{conv}").status_code == 200


def test_the_owner_cookie_is_http_only_and_renewed_with_the_same_value():
    """Renewed on every visit, so a daily reader does not lose the history a
    year after the first one."""
    fresh = TestClient(app)
    first = fresh.get("/api/conversations").headers["set-cookie"]
    assert "gr_owner=" in first and "HttpOnly" in first and "SameSite=Lax" in first
    again = fresh.get("/api/conversations").headers["set-cookie"]
    assert again.split(";")[0] == first.split(";")[0]


def test_another_sites_malformed_cookie_does_not_cost_the_history():
    """Cookies are shared by every app on the host (and every port of localhost)."""
    c = TestClient(app)
    conv = _events(c.post("/api/chat", json={"question": HOURS}))[0][1]["conversation_id"]
    token = c.cookies.get("gr_owner")
    raw = f'theme={{"dark":true}}; foo[bar]=1; gr_owner={token}'
    r = TestClient(app).get(f"/api/conversations/{conv}", headers={"cookie": raw})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_two_quick_ratings_do_not_collide():
    """👍 then 👎 in quick succession: both requests may find no rating yet."""
    import asyncio

    import httpx

    events = _chat(question=HOURS)
    message_id = events[-1][1]["message_id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", cookies=dict(client.cookies.items())) as c:
        replies = await asyncio.gather(*(
            c.put(f"/api/messages/{message_id}/feedback", json={"rating": r})
            for r in ("up", "down", "up", "down")
        ))
    assert [r.status_code for r in replies] == [200] * 4


def test_readyz_does_not_show_internals_publicly(monkeypatch):
    async def down():
        raise ConnectionError("password authentication failed for user grounded_rag")

    monkeypatch.setattr(health, "ping_db", down)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["db"] == "unavailable"
    assert "password" not in r.text


def test_an_escalated_answer_restarts_the_draft_and_records_the_model(monkeypatch):
    import asyncio

    from grounded_rag.db.models import Message
    from grounded_rag.db.session import SessionLocal

    cheap, strong = Scripted(tokens=("Tám giờ.",)), Scripted(tokens=("Tám giờ ", "[C1]."))
    cheap.model, strong.model = "cheap", "strong"
    monkeypatch.setattr(service, "get_llm_client", lambda: cheap)
    monkeypatch.setattr(service, "get_escalation_client", lambda: strong)
    events = _chat(question=HOURS)
    kinds = [k for k, _ in events]
    assert kinds.index("token") < kinds.index("retry") < len(kinds) - 1
    assert dict(events)["retry"] == {"reason": "no_citation"}
    done = events[-1][1]
    assert (done["status"], done["answer"]) == ("answered", "Tám giờ [C1].")
    # what the reader is told under the answer, then and after a reload
    assert (done["model"], done["escalated"], done["fallback"]) == ("strong", True, False)
    conv = client.get(f"/api/conversations/{events[0][1]['conversation_id']}").json()
    shown = conv["messages"][-1]
    assert (shown["model"], shown["escalated"], shown["fallback"]) == ("strong", True, False)

    async def saved() -> Message:
        async with SessionLocal() as s:
            return await s.get(Message, done["message_id"])

    msg = asyncio.run(saved())
    assert (msg.model, msg.escalated, msg.fallback) == ("strong", True, False)
