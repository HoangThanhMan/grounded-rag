from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from grounded_rag.types import Answer

CONFIG_NAME = r"^[A-Za-z0-9_-]+$"   # a file in configs/, never a path


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    config: str = Field(default="full", pattern=CONFIG_NAME)
    as_of: date | None = None       # read the law as of this day; default today


class ChatResponse(Answer):
    pass


class IngestRequest(BaseModel):
    source: str = "data/corpus"
    config: str = Field(default="full", pattern=CONFIG_NAME)
    recreate: bool = False


class IngestResponse(BaseModel):
    files: int
    chunks: int
    written: int


class ConfigSummary(BaseModel):
    """One row of GET /configs - which layers of defence a config turns on."""

    name: str
    guard_enabled: bool
    entailment_threshold: float
    corrective_enabled: bool
    min_score: float
    chunker: str
