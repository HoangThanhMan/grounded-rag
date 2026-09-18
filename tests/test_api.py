from pathlib import Path

from fastapi.testclient import TestClient

from grounded_rag import service
from grounded_rag.api.main import app
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import LLMUnavailable
from grounded_rag.ingest.pipeline import ingest

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok", "provider": "mock"}


def test_unknown_config_is_404():
    r = client.post("/chat", json={"question": "Nghỉ việc?", "config": "nope"})
    assert r.status_code == 404


def test_config_is_a_name_not_a_path():
    r = client.post("/chat", json={"question": "Nghỉ việc?", "config": "../secrets"})
    assert r.status_code == 422


def test_a_refusal_is_200_but_a_provider_outage_is_503(monkeypatch):
    ingest(Path("data/sample_corpus"), RunConfig.from_yaml("configs/baseline.yaml"))

    class Down:
        async def complete(self, *args, **kw):
            raise LLMUnavailable("connection refused")

    monkeypatch.setattr(service, "get_llm_client", lambda: Down())
    # baseline has no retrieval floor, so the LLM is always reached
    r = client.post("/chat", json={"question": "Thời giờ làm việc?", "config": "baseline"})
    assert r.status_code == 503
    assert "connection refused" in r.json()["detail"]


def test_configs_lists_every_yaml_with_its_guard_threshold():
    rows = client.get("/configs").json()
    assert {r["name"] for r in rows} == {"baseline", "threshold", "full", "agentic"}
    by_name = {r["name"]: r for r in rows}
    # the demo UI draws the entailment gauge against this number
    assert by_name["full"]["guard_enabled"] is True
    assert by_name["full"]["entailment_threshold"] == 0.50
    assert by_name["baseline"]["guard_enabled"] is False
    assert by_name["agentic"]["corrective_enabled"] is True


def test_demo_ui_is_served_from_the_api_itself():
    # one process, one origin, no CORS - see app/web/
    index = client.get("/")
    assert index.status_code == 200
    assert "grounded-rag" in index.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
