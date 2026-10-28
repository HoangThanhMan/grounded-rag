FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.cache/hf

# Exact versions from requirements.lock (`make lock`), so a rebuild next month
# installs what was tested. torch is the CPU build: the default CUDA wheels
# add ~3 GB that never load without a GPU. Installed before the code is
# copied, so a code change does not reinstall 2 GB of dependencies.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
        --extra-index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY alembic.ini ./
COPY alembic ./alembic

# Not root. The code stays root-owned and read-only to the server; what it
# writes - the model cache and uploads - are named volumes in
# docker-compose.yml, which start out owned like these directories.
ARG UID=1000
RUN useradd --uid "$UID" --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/.cache /app/data/uploads && chown -R app /app/.cache /app/data
USER app

EXPOSE 8000
# No curl in the slim image; python is already there. start-period covers
# the first start, when the models are downloaded into the cache.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
# Migrate, then serve. One replica: the rate limiter and the background
# indexer both live in this process.
# --no-access-log: the app writes its own, one JSON line per request with its id.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn grounded_rag.api.main:app --host 0.0.0.0 --port 8000 --no-access-log --timeout-graceful-shutdown 20"]
