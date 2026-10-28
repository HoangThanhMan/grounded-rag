from grounded_rag.config import RetrievalOptions, Settings, retrieval_options


def test_the_app_retrieves_with_the_legal_defaults():
    opts = retrieval_options()
    assert opts == RetrievalOptions(
        chunker="structural", hybrid=True, rerank=True, top_k_dense=20, top_k_sparse=20,
        rerank_candidates=20, top_n=5, min_score=0.30,
    )


def test_generation_and_history_defaults():
    # the defaults themselves: conftest overrides several through the environment
    default = {name: f.default for name, f in Settings.model_fields.items()}
    assert (default["temperature"], default["max_tokens"], default["history_turns"]) == (
        0.0, 512, 3)
    assert default["llm_base_url"] == "https://api.groq.com/openai/v1"
    assert default["database_url"] == "sqlite+aiosqlite:///./data/app.db"
    assert (default["max_upload_mb"], default["rate_limit_per_minute"]) == (10, 20)


def test_naive_retrieval_can_switch_the_floor_off():
    assert RetrievalOptions(min_score=None).min_score is None


def test_the_floor_is_set_from_the_environment(monkeypatch):
    from grounded_rag import config

    monkeypatch.setattr(config.settings, "retrieval_min_score", 0.12)
    assert retrieval_options().min_score == 0.12
