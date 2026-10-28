"""Settings from the environment (.env, never in git), and the retrieval
options the pipeline runs with."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMEndpoint(BaseModel):
    """One more OpenAI-compatible model: where it is, which one, how to ask.
    Set in .env as JSON - see LLM_FALLBACKS and LLM_ESCALATION."""

    base_url: str
    model: str
    api_key: str = ""
    # per model: gemini-3.5-flash-lite rejects "none", gemini-3.1-flash-lite wants it
    reasoning_effort: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # mock runs the whole app with no key and no model weights: a canned LLM,
    # a hashing embedder and a lexical reranker. An unknown value is a startup
    # error, never a silent fallback to mock.
    llm_provider: Literal["mock", "openai"] = "mock"
    # Any OpenAI-compatible endpoint: Groq, Gemini, Ollama, vLLM, OpenAI.
    # .env.example has a preset for each.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "mock-model"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    # Sent as `reasoning_effort` when set ("none", "low", ...). Thinking
    # tokens count against max_tokens.
    llm_reasoning_effort: str = ""
    # Asked in order when the model before is unavailable - a spent quota, an
    # overloaded server - but only before the first token reaches the user.
    llm_fallbacks: list[LLMEndpoint] = Field(default_factory=list)
    # A stronger model, asked once more when the first answer fails the
    # citation check after retrieval found good sources. None = no second try.
    llm_escalation: LLMEndpoint | None = None
    temperature: float = 0.0
    max_tokens: int = 512
    # Earlier question/answer pairs used to rewrite a follow-up question
    history_turns: int = Field(default=3, ge=0)
    # "Today", when a question names no date, is today where the law applies -
    # not on the server's UTC clock, seven hours behind in the morning.
    law_timezone: str = "Asia/Ho_Chi_Minh"

    # ":memory:" runs Qdrant's embedded mode - the real code path, no server
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "grounded_rag"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # The rerank score below which a source is dropped - and with none left,
    # the question refused before any LLM call. On bge-reranker-v2-m3's
    # sigmoid scale; another reranker needs its own value.
    retrieval_min_score: float = 0.30
    # Model calls (embed, rerank) running at once - see compute.py. Each
    # already uses every core through torch's intra-op threads, so 1 is right
    # on a CPU box; more only helps with spare cores and a smaller torch pool.
    model_workers: int = Field(default=1, ge=1)

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    # Postgres connections kept open; 0 = a new connection per session, for
    # callers that run several event loops (the tests)
    database_pool_size: int = Field(default=5, ge=0)
    upload_dir: Path = Path("data/uploads")
    max_upload_mb: int = 10
    # Indexed at startup, file by file, when the document table does not know
    # them yet: what makes `docker compose up` answer questions on first run.
    auto_seed_dir: str = ""

    # Requests per minute per client on /api/chat; 0 turns the limit off
    rate_limit_per_minute: int = Field(default=20, ge=0)
    # Behind nginx the client address is the last X-Forwarded-For hop.
    # Off by default: trusted from anyone else, the header is a free bypass.
    trust_proxy: bool = False
    # Document upload and delete are off until a key is set
    admin_api_key: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    # Mark the anonymous-owner cookie Secure: true once the site is on HTTPS
    cookie_secure: bool = False


class RetrievalOptions(BaseModel):
    """How a question is turned into sources. The app runs the defaults; the
    evaluation also runs a naive RAG through the same code by switching the
    legal-specific parts off."""

    chunker: Literal["recursive", "structural"] = "structural"
    hybrid: bool = True             # dense + BM25; false = dense only
    rerank: bool = True
    top_k_dense: int = 20
    top_k_sparse: int = 20
    rerank_candidates: int = 20     # fused list is cut here before the cross-encoder
    top_n: int = 5
    # Below this rerank score a source is dropped; no source left means no
    # LLM call. None = no floor.
    min_score: float | None = 0.30


def retrieval_options() -> RetrievalOptions:
    return RetrievalOptions(min_score=settings.retrieval_min_score)


settings = Settings()
