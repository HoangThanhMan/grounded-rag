"""Tests run on the mock provider whatever .env says: no keys, no model
weights, no network. Qdrant tests use the embedded ':memory:' mode.

Set before anything imports grounded_rag.config, which reads the environment
once at import time.

Every process - the API, the CLI, the eval - runs from the repository root,
where `data/` lives. The tests do too, wherever pytest was started from."""

import os
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"
os.environ["QDRANT_URL"] = ":memory:"

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)

# Written against the research pipeline (configs/, the NLI guard, Langfuse)
# and rewritten with it: the service and concurrency tests come back with the
# new pipeline, the API tests with the new routes.
collect_ignore = ["test_api.py", "test_service_smoke.py", "test_concurrency.py", "test_tracing.py"]
