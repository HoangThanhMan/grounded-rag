"""Tests run on the mock provider whatever .env says: no keys, no model
weights, no network. Qdrant tests use the embedded ':memory:' mode.

Set before anything imports grounded_rag.config, which reads the environment
once at import time."""

import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["QDRANT_URL"] = ":memory:"
