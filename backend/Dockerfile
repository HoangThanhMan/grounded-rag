FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.cache/hf

COPY pyproject.toml ./
COPY src ./src
# torch defaults to the CUDA build: 554 MB of torch plus ~3 GB of nvidia-*
# wheels that never get loaded without a GPU. Install the CPU build first and
# the extras below resolve against it. For a GPU image, drop this line.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ".[models,obs]"

COPY alembic.ini ./
COPY alembic ./alembic

# Not root. The code stays root-owned and read-only to the server; what it
# writes - the model cache, uploads, the corpus volume - are bind mounts in
# docker-compose.yml, so the uid defaults to the usual first user on a Linux
# host, who owns them. Elsewhere: docker compose build --build-arg UID=$(id -u)
ARG UID=1000
RUN useradd --uid "$UID" --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/.cache /app/data && chown app /app/.cache /app/data
USER app

EXPOSE 8000
# No curl in the slim image; python is already there. start-period covers
# the first start, when the models are downloaded into the cache.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
# Migrate, then serve. One replica: the rate limiter and the background
# indexer both live in this process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn grounded_rag.api.main:app --host 0.0.0.0 --port 8000"]
