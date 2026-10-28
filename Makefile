.PHONY: python install dev-install up up-qdrant up-api down run corpus ingest seed test lint fmt

CONFIGS := baseline threshold full agentic
PORT ?= 8000

# Use the project venv when there is one, so no target depends on you having
# remembered to activate it. VIRTUAL_ENV wins if you did activate something.
ifdef VIRTUAL_ENV
PY := $(VIRTUAL_ENV)/bin/python
else ifneq ($(wildcard .venv/bin/python),)
PY := .venv/bin/python
else
PY := python3
endif

install:      ## runtime deps only
	$(PY) -m pip install -e backend

dev-install:  ## everything needed to actually run the pipeline
	$(PY) -m pip install -e "backend[models,obs,dev]"

up:           ## qdrant + langfuse only - the API runs natively with `make run`
	docker compose up -d qdrant langfuse

up-qdrant:    ## qdrant alone, all `make ingest` and `make eval` need
	docker compose up -d qdrant

up-api:       ## also build and run the API in a container (slow first build)
	docker compose up -d --build api

up-ollama:    ## + Ollama serving an open model on CPU (set LLM_PROVIDER=ollama)
	docker compose --profile ollama up -d ollama

up-gpu:       ## + vLLM serving an open model (NVIDIA GPU only)
	docker compose --profile gpu up -d

down:
	docker compose down

run:          ## api + demo UI on :$(PORT) (open http://localhost:8000)
	$(PY) -m uvicorn grounded_rag.api.main:app --reload --port $(PORT)

corpus:       ## download the laws from Công báo -> data/corpus/*.md
	$(PY) scripts/prepare_corpus.py

ingest:       ## index the real corpus in data/corpus/ (both chunkers)
	$(PY) -m grounded_rag.ingest.pipeline --source data/corpus --config configs/full.yaml
	$(PY) -m grounded_rag.ingest.pipeline --source data/corpus --config configs/baseline.yaml

# Refuses unless the server reports the mock provider. /ingest itself only
# ever adds to an index (`recreate` is CLI-only) and is off until the server
# has an ADMIN_API_KEY - the same key has to be in this shell.
seed:         ## load the sample corpus into a RUNNING mock server (in-memory, lost on restart)
	@curl -fsS localhost:$(PORT)/healthz 2>/dev/null | grep -q '"provider":"mock"' \
	  || { echo "refusing: :$(PORT) is not running the mock provider (or is not up)."; \
	       echo "  start it with:  LLM_PROVIDER=mock ADMIN_API_KEY=dev make run"; exit 1; }
	@test -n "$$ADMIN_API_KEY" \
	  || { echo "refusing: set ADMIN_API_KEY to the key the server was started with."; exit 1; }
	@curl -fsS -X POST localhost:$(PORT)/ingest -H 'content-type: application/json' \
	  -H "x-api-key: $$ADMIN_API_KEY" \
	  -d '{"source":"data/sample_corpus","config":"full"}' && echo ""

test:
	$(PY) -m pytest -q backend/tests

lint:
	$(PY) -m ruff check backend/src backend/tests backend/alembic

fmt:
	$(PY) -m ruff format backend/src backend/tests

python:       ## which interpreter every target above will use
	@echo $(PY)
