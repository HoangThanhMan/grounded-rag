"""Settings from the environment, plus per-run YAML configs.

Two layers on purpose:
  - Settings  -> secrets and infrastructure, from .env, never in git
  - RunConfig -> pipeline behaviour, from configs/*.yaml, committed so an
                 eval run is reproducible from the repo alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    temperature: float = 0.0
    max_tokens: int = 512
    # Earlier question/answer pairs used to rewrite a follow-up question
    history_turns: int = Field(default=3, ge=0)

    # ":memory:" runs Qdrant's embedded mode - the real code path, no server
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "grounded_rag"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # Model calls (embed, rerank) running at once - see compute.py. Each
    # already uses every core through torch's intra-op threads, so 1 is right
    # on a CPU box; more only helps with spare cores and a smaller torch pool.
    model_workers: int = Field(default=1, ge=1)

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    upload_dir: Path = Path("data/uploads")
    max_upload_mb: int = 10
    # Indexed at startup, file by file, when the document table does not know
    # them yet: what makes `docker compose up` answer questions on first run.
    auto_seed_dir: str = ""

    # Requests per minute per client on /api/chat; 0 turns the limit off
    rate_limit_per_minute: int = Field(default=20, ge=0)
    # Behind nginx the client address is the first X-Forwarded-For hop.
    # Off by default: trusted from anyone else, the header is a free bypass.
    trust_proxy: bool = False
    # Document upload and delete are off until a key is set
    admin_api_key: str = ""
    cors_origins: list[str] = Field(default_factory=list)


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
    return RetrievalOptions()


class RetrievalConfig(BaseModel):
    chunker: Literal["recursive", "structural"] = "recursive"
    hybrid: bool = True             # dense + BM25; false = dense only, for ablation
    top_k_dense: int = 20
    top_k_sparse: int = 20
    rerank_candidates: int = 20     # fused list is cut here before the cross-encoder
    rerank_to: int = 5
    min_score: float = 0.0


class CorrectiveConfig(BaseModel):
    """Corrective retrieval: one bounded rewrite-and-retry when retrieval is weak."""

    enabled: bool = False
    confident_score: float = 0.60   # top rerank score that needs no second attempt
    max_rounds: int = Field(default=1, ge=0, le=3)
    max_queries: int = Field(default=3, ge=1, le=5)


class GenerationConfig(BaseModel):
    temperature: float = 0.0
    max_tokens: int = 512
    require_citations: bool = True


class GuardConfig(BaseModel):
    enabled: bool = False
    entailment_threshold: float = 0.60
    max_regenerations: int = 1
    on_unsupported: Literal["drop_claim", "abstain_all"] = "drop_claim"


class RunConfig(BaseModel):
    name: str = "unnamed"
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    corrective: CorrectiveConfig = Field(default_factory=CorrectiveConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    guard: GuardConfig = Field(default_factory=GuardConfig)
    # Hard ceiling on LLM calls per question, planner and regeneration
    # included. The loops are bounded by construction; this is the backstop.
    max_llm_calls: int = Field(default=4, ge=1)

    @classmethod
    def from_yaml(cls, path: str | Path) -> RunConfig:
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)


settings = Settings()
