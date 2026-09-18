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

    # mock | ollama | vllm | openai | gemini | anthropic. An unknown value is a
    # startup error, never a silent fallback to mock.
    llm_provider: Literal["mock", "ollama", "vllm", "openai", "gemini", "anthropic"] = "mock"
    llm_model: str = "mock-model"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    # Sent as `reasoning_effort` to OpenAI-compatible providers when set
    # ("none", "low", ...). Thinking tokens count against max_tokens.
    llm_reasoning_effort: str = ""
    # USD per million tokens, so meta.cost_usd means something for paid APIs
    llm_input_usd_per_mtok: float = 0.0
    llm_output_usd_per_mtok: float = 0.0

    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8001/v1"
    vllm_api_key: str = "EMPTY"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # ":memory:" runs Qdrant's embedded mode - the real code path, no server
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "grounded_rag"

    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    nli_model: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

    # Threshold of the NLI *measuring instrument* in eval/run.py. The guard's
    # own threshold lives in configs/*.yaml.
    entailment_threshold: float = 0.50

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"


class RetrievalConfig(BaseModel):
    chunker: Literal["recursive", "structural"] = "recursive"
    hybrid: bool = True             # dense + BM25; false = dense only, for ablation
    top_k_dense: int = 20
    top_k_sparse: int = 20
    rerank_candidates: int = 20     # fused list is cut here before the cross-encoder
    rerank_to: int = 5
    min_score: float = 0.0


class CorrectiveConfig(BaseModel):
    """Corrective retrieval - see docs/adr/0005-corrective-retrieval-loop.md."""

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
