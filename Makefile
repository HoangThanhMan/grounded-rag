.PHONY: python install lock up down dev-api dev-web test lint fmt ingest eval

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

install:      ## backend with the models, frontend packages
	$(PY) -m pip install -e "backend[models,obs,dev]"
	cd frontend && npm ci

lock:         ## pin the image's Python dependencies (needs uv)
	cd backend && uv pip compile pyproject.toml --extra models --extra obs \
	  --python-version 3.12 --python-platform x86_64-manylinux_2_28 --torch-backend cpu \
	  --no-header -o requirements.lock

up:           ## the whole app in containers -> http://localhost:8080
	docker compose up -d --build

down:
	docker compose down

dev-api:      ## API on :$(PORT) with reload; Qdrant from `docker compose up -d qdrant`
	$(PY) -m alembic -c backend/alembic.ini upgrade head
	$(PY) -m uvicorn grounded_rag.api.main:app --reload --port $(PORT)

dev-web:      ## Vite on :5173, proxying /api to :$(PORT)
	cd frontend && npm run dev

test:
	$(PY) -m pytest -q backend/tests
	cd frontend && npm test

lint:
	$(PY) -m ruff check backend/src backend/tests backend/alembic eval
	cd frontend && npm run typecheck

fmt:
	$(PY) -m ruff format backend/src backend/tests eval

ingest:       ## both indexes the evaluation needs, from data/corpus
	$(PY) -m grounded_rag.ingest.pipeline --source data/corpus --chunker structural
	$(PY) -m grounded_rag.ingest.pipeline --source data/corpus --chunker recursive

eval:         ## naive RAG vs the app on 100 test questions, then the hard ones -> eval/results/
	$(PY) -m eval.run --system naive
	$(PY) -m eval.run --system app
	$(PY) -m eval.run --system naive --set hard
	$(PY) -m eval.run --system app --set hard
	$(PY) -m eval.report > eval/results/summary.md
	cat eval/results/summary.md

python:       ## which interpreter every target above will use
	@echo $(PY)
