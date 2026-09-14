FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.cache/hf

COPY pyproject.toml ./
COPY src ./src
# torch defaults to the CUDA build: 554 MB of torch plus ~3 GB of nvidia-*
# wheels that never get loaded without a GPU. Install the CPU build first and
# the extras below resolve against it. For a GPU image, drop these two lines.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -e ".[models,obs]"

COPY configs ./configs
COPY eval ./eval
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "grounded_rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
