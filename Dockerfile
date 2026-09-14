FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.cache/hf

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[models,obs]"

COPY configs ./configs
COPY eval ./eval
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "grounded_rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
