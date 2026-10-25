# 02 — Tech stack

Mọi công nghệ dự án dùng: vai trò, nằm ở đâu, vì sao chọn, và cái đã bị loại.
Phiên bản "khai báo" lấy từ `pyproject.toml` / `docker-compose.yml`; phiên bản
"trong `.venv`" là bản đang cài trên máy phát triển ngày 2026-10-17.

## Ngôn ngữ & runtime

| Thứ | Phiên bản | Ghi chú |
|---|---|---|
| Python | `>=3.12` (`pyproject.toml`); `.python-version` = 3.12; `.venv` local = 3.14 | Code dùng cú pháp generic PEP 695 (`def run_model[**P, R]`, `def _batched[T]`) nên **bắt buộc ≥ 3.12**. CI chạy cả 3.12 và 3.14 |
| JavaScript thuần | — | `app/web/app.js`, không framework, không build step |

## Thư viện runtime (luôn cài: `make install`)

| Thư viện | Khai báo | Trong `.venv` | Dùng để | File chính |
|---|---|---|---|---|
| FastAPI | `>=0.115` | 0.141 | HTTP API, SSE, OpenAPI tại `/docs`, phục vụ file tĩnh | `api/main.py`, `api/routes_*.py` |
| Uvicorn | `>=0.32` | 0.52 | ASGI server | `make run`, `Dockerfile` |
| Pydantic v2 | `>=2.9` | 2.13 | Mọi kiểu dữ liệu domain và schema API, validate YAML config | `types.py`, `config.py`, `api/schemas.py` |
| pydantic-settings | `>=2.6` | 2.15 | Đọc biến môi trường + `.env` thành `Settings` | `config.py` |
| httpx | `>=0.27` | 0.28 | Gọi LLM qua HTTP thẳng (không dùng SDK); `MockTransport` trong test; `ASGITransport` cho test API | `generation/llm_client.py` |
| PyYAML | `>=6.0` | 6.0 | Đọc `configs/*.yaml` và front matter của văn bản | `config.py`, `ingest/loaders.py` |
| qdrant-client | `>=1.12` | 1.19 | Vector store; chế độ `:memory:` cho test | `retrieval/store.py` |

## Extra `models` — model thật (nặng, vài GB)

| Thư viện | Khai báo | Trong `.venv` | Dùng để |
|---|---|---|---|
| torch | `>=2.5` | 2.14 (CPU) | Backend cho mọi model. Dockerfile cài bản CPU trước để tránh ~3 GB wheel CUDA |
| transformers | `>=4.46` | 5.17 | Reranker (`AutoModelForSequenceClassification`), NLI (`pipeline("text-classification")`) |
| sentence-transformers | `>=3.3` | 6.0 | Embedder bge-m3 |
| pymupdf | `>=1.24` | 1.28 | Đọc PDF (loader và `scripts/prepare_corpus.py`) |

### Các model

| Model | Vai trò | Kích thước (RAM) | Cấu hình | File |
|---|---|---|---|---|
| `BAAI/bge-m3` | Embedding dense, 1024 chiều, đa ngữ | ~2,2 GB | `EMBEDDING_MODEL` | `retrieval/embedder.py` |
| `BAAI/bge-reranker-v2-m3` | Cross-encoder rerank, điểm sigmoid 0–1 | ~2,2 GB | `RERANKER_MODEL` | `retrieval/reranker.py` |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | NLI cho guard và thước đo eval, ~280M tham số | ~1,1 GB | `NLI_MODEL` | `guard/nli_verifier.py` |
| `gemini-3.1-flash-lite` | Generator dùng cho benchmark chính | API | `LLM_MODEL` | `generation/llm_client.py` |
| `qwen2.5:3b-instruct-q4_K_M` | Generator mở trên CPU qua Ollama (đã thử, yếu) | ~1,9 GB | `LLM_MODEL` | — |
| `Qwen/Qwen2.5-7B-Instruct-AWQ` | Generator mở trên GPU qua vLLM | GPU | service `vllm` | `docker-compose.yml` |

Đỉnh RAM khi truy vấn với cả ba model nạp sẵn: ~4,5 GB (đo trên i7-11800H,
[../09-runbook.md](../09-runbook.md)).

## Extra `eval`

| Thư viện | Khai báo | Dùng để |
|---|---|---|
| ragas | `>=0.4,<0.5` (0.4.3) | Bốn metric LLM-judge: faithfulness, answer relevancy, context precision, context recall (`eval/ragas_eval.py`) |
| openai | `>=1.40` | Client cho giám khảo RAGAS qua endpoint OpenAI-compatible |
| langchain-community | `<0.4` | Chỉ vì ragas 0.4.3 import một module đã bị xóa ở 0.4. **Pipeline không dùng LangChain** |

## Extra `obs`

| Thư viện | Khai báo | Dùng để |
|---|---|---|
| prometheus-client | `>=0.21` | `/metrics`: histogram từng bước, counter câu trả lời, token, lời gọi LLM (`observability/metrics.py`). Không cài thì mọi hàm là no-op |
| langfuse | `>=2.53,<3` (SDK v2) | Đẩy mỗi câu trả lời thành một trace (`observability/tracing.py`). **Lưu ý:** `.venv` local đang có langfuse 4.15, không khớp khai báo — xem [13](13-known-gaps.md) |

## Extra `dev`

| Thư viện | Dùng để |
|---|---|
| pytest + pytest-asyncio | Test, kể cả async |
| ruff | Lint (`E`, `F`, `I`, `UP`, `B`), độ dài dòng 100 |

## Hạ tầng (Docker Compose)

| Service | Image | Cổng | Bật bằng | Vai trò |
|---|---|---|---|---|
| `qdrant` | `qdrant/qdrant:v1.19.1` | 6333 | `make up-qdrant` | Vector store; dữ liệu ở `./qdrant_storage` |
| `api` | build từ `Dockerfile` | 8000 | `make up-api` | API trong container (thường chạy native bằng `make run`) |
| `langfuse` + `langfuse-db` | `langfuse/langfuse:2`, `postgres:16-alpine` | 3000 | `make up` | Tracing LLM (tùy chọn); secret là giá trị dev |
| `ollama` | `ollama/ollama:0.34.0` (pin) | 11434 | `make up-ollama` (profile `ollama`) | Model mở trên CPU, `mem_limit: 3g` |
| `vllm` | `vllm/vllm-openai:v0.29.0` | 8001 | `make up-gpu` (profile `gpu`) | Model mở trên GPU NVIDIA |

## Provider LLM

| `LLM_PROVIDER` | Client | Endpoint |
|---|---|---|
| `mock` | `MockClient` | Không có — chép lại đoạn đầu tiên kèm `[C1]` |
| `ollama` | `OpenAICompatClient` | `{OLLAMA_BASE_URL}/v1/chat/completions` |
| `vllm` | `OpenAICompatClient` | `{VLLM_BASE_URL}/chat/completions` |
| `openai` | `OpenAICompatClient` | `{OPENAI_BASE_URL}/chat/completions` |
| `gemini` | `OpenAICompatClient` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `anthropic` | `AnthropicClient` | `https://api.anthropic.com/v1/messages` |

Tên provider sai là **lỗi khởi động** (`Literal[...]` trong `Settings`), không
lặng lẽ rơi về mock.

## CI/CD & công cụ

| Thứ | Dùng để |
|---|---|
| GitHub Actions (`.github/workflows/ci.yml`) | Lint, test, kiểm tra dataset, smoke eval `full` + `agentic` trên mock; ma trận Python 3.12 / 3.14; upload report làm artifact |
| Makefile | Mọi lệnh thường dùng; tự chọn `.venv/bin/python` nếu có |
| Dockerfile | `python:3.12-slim`, torch CPU, user không phải root (UID 1000), `HEALTHCHECK` gọi `/healthz` |

## Kỹ thuật & thuật toán (không phải thư viện)

| Kỹ thuật | Ở đâu | Ghi chú |
|---|---|---|
| BM25 (`k1=1.2`, `b=0.75`) + tokenizer âm tiết + bigram | `retrieval/lexical.py` | Tự viết; trong Qdrant là sparse vector với `Modifier.IDF` |
| Reciprocal Rank Fusion (`k=60`) | `retrieval/hybrid.py` | Gộp dense và sparse |
| CRAG-style corrective retrieval | `retrieval/corrective.py` | Tự viết, có trần lời gọi |
| Chunk theo cấu trúc Điều/Khoản | `ingest/chunkers.py` | Regex trên văn bản luật |
| NLI entailment + luật con số + premise views | `guard/nli_verifier.py` | — |
| Pool luồng ưu tiên request đến trước | `compute.py` | `PriorityQueue` theo thời điểm đến |
| ID chunk theo hash nội dung, point id `uuid5` | `ingest/chunkers.py`, `retrieval/store.py` | Ingest idempotent |

## Cố tình không dùng

| Không dùng | Vì sao | ADR |
|---|---|---|
| LangChain / LlamaIndex / LangGraph / Haystack / DSPy | Pipeline vài bước, vòng lặp duy nhất có hai nhánh; framework che mất phần đáng giải thích | [0005](../adr/0005-corrective-retrieval-loop.md) |
| LLM-as-judge cho guard | Đắt, không tất định, cùng họ lỗi với generator | [0001](../adr/0001-nli-over-llm-judge.md) |
| Chroma, FAISS, pgvector, Pinecone | Chroma: sparse/hybrid yếu · FAISS: không có metadata filter · pgvector: thêm một service không cần · Pinecone: cloud, không chạy offline | [0002](../adr/0002-qdrant-as-vector-store.md) |
| Sparse vector của bge-m3 | BM25 không cần model, chạy được cả ở mock | [0006](../adr/0006-bm25-sparse-retrieval.md) |
| Fine-tune generator (Unsloth, QLoRA) | Dạy model trả lời từ trí nhớ, ngược với grounding | [0007](../adr/0007-no-generator-fine-tuning.md) |
| SDK của OpenAI/Anthropic trong pipeline | httpx thẳng để giao thức nhìn thấy được, ít phụ thuộc | — |
| HyDE | Cố tình sinh nội dung bịa để dẫn truy xuất | [0005](../adr/0005-corrective-retrieval-loop.md) |

---

[← 01 — Tổng quan](01-overview.md) · [Handbook](README.md) · [03 — Kiến trúc →](03-architecture.md)
