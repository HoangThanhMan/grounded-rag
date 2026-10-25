# 10 — Cấu hình & vận hành

## 1. Biến môi trường — `Settings` (`src/grounded_rag/config.py`)

Đọc một lần lúc import, từ môi trường và `.env` (biến môi trường ghi đè `.env`).
Mẫu: `.env.example`. Trường lạ bị bỏ qua.

### LLM

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` \| `ollama` \| `vllm` \| `openai` \| `gemini` \| `anthropic`. Sai tên → lỗi khởi động. **`mock` bật mock cho mọi thành phần** (embedder, store, reranker, NLI) |
| `LLM_MODEL` | `mock-model` | Tên model gửi cho provider |
| `LLM_TIMEOUT_S` | 60 | Timeout mỗi lời gọi HTTP |
| `LLM_MAX_RETRIES` | 2 | Số lần thử lại với 408/429/5xx và lỗi mạng |
| `LLM_REASONING_EFFORT` | rỗng | Gửi `reasoning_effort` (vd `none`) cho provider OpenAI-compatible; rỗng thì không gửi |
| `LLM_INPUT_USD_PER_MTOK`, `LLM_OUTPUT_USD_PER_MTOK` | 0 | Đơn giá để tính `meta.cost_usd` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `VLLM_BASE_URL`, `VLLM_API_KEY` | `http://localhost:8001/v1`, `EMPTY` | |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | `https://api.openai.com/v1`, rỗng | Mọi server nói giao thức OpenAI |
| `GEMINI_API_KEY` | rỗng | |
| `ANTHROPIC_API_KEY` | rỗng | |
| `ANTHROPIC_SEND_TEMPERATURE` | false | Claude Opus 4.7+ từ chối mọi `temperature`, Sonnet 5.x/Haiku 5.5 từ chối giá trị khác mặc định |

### Vector store & model

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | `:memory:` = Qdrant nhúng, không cần server (test) |
| `QDRANT_COLLECTION` | `grounded_rag` | Tiền tố; collection thật là `<tiền tố>_<chunker>` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | |
| `NLI_MODEL` | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | Dùng cho cả guard và thước đo eval |
| `MODEL_WORKERS` | 1 | Số lời gọi model chạy song song (`compute.py`). 1 là đúng trên CPU |
| `NLI_CACHE_SIZE` | 4096 | Số cặp (premise, mệnh đề) cache LRU |

### Eval, admin, observability

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `ENTAILMENT_THRESHOLD` | 0.50 | τ của **thước đo** eval (τ của guard nằm trong YAML) |
| `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY` | rỗng | Giám khảo RAGAS (đọc bằng `os.environ` trong `eval/ragas_eval.py`) |
| `ADMIN_API_KEY` | rỗng | Rỗng = `POST /ingest` tắt (403) |
| `DATA_ROOT` | `data` | `/ingest` chỉ đọc thư mục dưới đây |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | rỗng, rỗng, `http://localhost:3000` | Có đủ key + extra `obs` thì export trace |

## 2. Cấu hình chạy — `RunConfig` (`configs/*.yaml`)

| Khóa | Kiểu / mặc định | Nghĩa |
|---|---|---|
| `name` | `"unnamed"` | Hiện trong `meta.config`, report, metric |
| `retrieval.chunker` | `recursive` \| `structural` | Chọn chunker **và** collection |
| `retrieval.hybrid` | true | false = chỉ dense (ablation) |
| `retrieval.top_k_dense`, `top_k_sparse` | 20, 20 | Số ứng viên mỗi nhánh |
| `retrieval.rerank_candidates` | 20 | Cắt danh sách RRF trước cross-encoder |
| `retrieval.rerank_to` | 5 | Số đoạn đưa cho LLM |
| `retrieval.min_score` | 0.0 | Floor trên điểm rerank |
| `corrective.enabled` | false | Bật vòng sửa lỗi |
| `corrective.confident_score` | 0.60 | Đủ tự tin thì bỏ qua vòng sửa |
| `corrective.max_rounds` | 1 (0–3) | |
| `corrective.max_queries` | 3 (1–5) | |
| `generation.temperature` | 0.0 | |
| `generation.max_tokens` | 512 | Model "thinking" có thể tiêu hết phần này |
| `generation.require_citations` | true | Khai báo; hiện **không có code nào đọc** trường này (prompt luôn bắt trích dẫn) |
| `guard.enabled` | false | |
| `guard.entailment_threshold` | 0.60 (YAML dùng 0.50) | τ |
| `guard.max_regenerations` | 1 | |
| `guard.on_unsupported` | `drop_claim` \| `abstain_all` | |
| `max_llm_calls` | 4 (≥1) | Trần lời gọi LLM mỗi câu hỏi |

Bốn file có sẵn: `baseline` (không floor, không guard, recursive), `threshold`
(+ floor 0.30), `full` (+ guard τ 0.50, structural), `agentic` (+ corrective).
Thêm cấu hình mới = thêm file YAML; API và UI tự nhận.

## 3. Makefile

Mọi target chạy bằng `$(PY)`: `$VIRTUAL_ENV/bin/python` nếu đã activate, không
thì `.venv/bin/python` nếu có, không thì `python3`. `make python` in ra cái đang dùng.

| Nhóm | Target | Làm gì |
|---|---|---|
| Cài đặt | `install` | `pip install -e .` (chỉ runtime) |
| | `dev-install` | `pip install -e ".[models,eval,obs,dev]"` |
| Chạy | `run` | `uvicorn grounded_rag.api.main:app --reload --port $(PORT)` (mặc định 8000) |
| | `seed` | `POST /ingest data/sample_corpus` vào server mock đang chạy (cần `ADMIN_API_KEY`) |
| Dữ liệu | `corpus` | `scripts/prepare_corpus.py` — tải từ Công báo |
| | `ingest` | Index `data/corpus` cho cả `full` (structural) và `baseline` (recursive) |
| | `check-dataset` | Kiểm tra dataset với corpus |
| Đánh giá | `eval` | `full` trên 80 câu test → `reports/full.json` |
| | `eval-all` | Bốn cấu hình + bảng |
| | `ragas` | RAGAS cho bốn report (cần `JUDGE_*`) |
| | `closed-book` | Ablation không tài liệu, 20 câu |
| | `calibrate` | Hiệu chỉnh τ |
| | `nli-probe` | Probe 24 cặp |
| Chất lượng | `test`, `lint`, `fmt` | pytest, ruff check, ruff format |
| Docker | `up` | qdrant + langfuse |
| | `up-qdrant` | chỉ qdrant (đủ cho ingest, run, eval) |
| | `up-api` | build và chạy API trong container |
| | `up-ollama` | Ollama (profile `ollama`) |
| | `up-gpu` | vLLM (profile `gpu`) |
| | `down` | `docker compose down` |

## 4. Docker

### `Dockerfile`

```
python:3.12-slim
  → COPY pyproject.toml, src
  → pip install torch (index CPU)          # tránh ~3 GB wheel nvidia-*
  → pip install -e ".[models,obs]"
  → COPY configs, eval, app
  → useradd app (UID 1000, build-arg UID) ; chown /app/.cache ; USER app
  → HEALTHCHECK mỗi 15 s: python urllib → /healthz (start-period 60 s cho lần tải model đầu)
  → uvicorn ... --host 0.0.0.0 --port 8000
```

Code thuộc root, chỉ đọc với server; thứ duy nhất server ghi là cache model
(`HF_HOME=/app/.cache/hf`, bind mount `./.cache`). Lưu ý: image **không** copy
`data/`; compose mount `./data:/app/data`.

### `docker-compose.yml`

Xem bảng service ở [02](02-tech-stack.md#hạ-tầng-docker-compose). Service `api`
dùng `env_file: .env`, ghi đè `QDRANT_URL=http://qdrant:6333` và
`VLLM_BASE_URL=http://vllm:8000/v1`, chờ `qdrant` healthy.

Cách chạy khuyến nghị khi phát triển: **chỉ Qdrant trong Docker, API chạy native**
(`make up-qdrant && make run`) — build image lần đầu tốn thời gian và dung lượng.

## 5. CI — `.github/workflows/ci.yml`

Chạy trên mọi `push` và `pull_request`, ma trận Python **3.12** và **3.14**,
`LLM_PROVIDER=mock`:

| Bước | Lệnh |
|---|---|
| Install | `pip install -e ".[dev]"` (cache pip) |
| Lint | `ruff check src eval tests app scripts` |
| Unit tests | `pytest -q` |
| Evaluation dataset | `python scripts/check_dataset.py` |
| Pipeline smoke test (mock) | `eval.run --config configs/full.yaml --dataset questions.sample.jsonl --ingest data/sample_corpus --gate` (ngưỡng bị bỏ qua trên tập mẫu) |
| Corrective config | như trên với `configs/agentic.yaml` |
| Upload artifact | `reports/ci-*.json` |

CI **không** cài model thật và không gọi LLM thật. Chưa có bước CD/deploy.

## 6. Observability

### `meta.steps` trong mỗi câu trả lời

`observability/tracing.py::trace(name, **attrs)` là context manager: đo
`perf_counter`, ghi `Step` vào list của `collect_steps()` (contextvar của
request), đẩy histogram Prometheus, log debug. Vì contextvar được copy vào luồng
model (`compute.run_model`), span chạy trong pool vẫn thuộc đúng request.

### Prometheus — `GET /metrics`

| Metric | Loại | Nhãn |
|---|---|---|
| `grounded_rag_step_seconds` | Histogram (0.01 … 16 s) | `step` |
| `grounded_rag_answers_total` | Counter | `config`, `status`, `reason` |
| `grounded_rag_llm_tokens_total` | Counter | `config` |
| `grounded_rag_llm_calls_total` | Counter | `config` |

Chưa có Prometheus server hay Grafana trong compose — chỉ có endpoint.

### Langfuse

`export(question, answer)` gửi một trace mỗi câu trả lời: span mỗi bước,
`generation` cho bước sinh, score `claims_supported` và `entailment` từng mệnh đề.
Best effort: lỗi chỉ ghi warning. Viết cho **SDK v2** (`client.trace(...)`) và
server `langfuse:2`; test dùng client giả; **chưa kiểm chứng trên UI thật**
([13](13-known-gaps.md)).

### Log

`logging.basicConfig(level=INFO)` trong `api/main.py`. Logger:
`grounded_rag.service` (cảnh báo bị cắt `max_tokens`, văn bản thô ở mức debug),
`grounded_rag.corrective`, `grounded_rag.trace`. Log dạng text, chưa có
request-id (kế hoạch S2).

## 7. Tài nguyên & hiệu năng (CPU i7-11800H)

| | Giá trị |
|---|---|
| RAM khi ingest | ~3,6 GB |
| RAM đỉnh khi truy vấn (3 model) | ~4,5 GB |
| Thêm qwen2.5:3b qua Ollama | +1,9 GB (máy 7 GB phải swap) |
| Ingest 1.241 chunk structural | 4 phút 20 giây |
| `retrieve` mỗi câu | 5–12 s (cross-encoder 20 ứng viên) |
| Một lượt eval 4 cấu hình × 80 câu với Gemini | ~4 giờ |

## 8. Xử lý sự cố nhanh

Bảng đầy đủ ở [../09-runbook.md](../09-runbook.md#xử-lý-sự-cố). Năm lỗi hay gặp nhất:

| Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|
| Mọi câu `no_context` khi chạy eval với mock | Store mock nằm trong tiến trình khác | Thêm `--ingest data/sample_corpus` |
| Mọi câu `no_context` với model thật | Chưa ingest, `as_of` ngoài hiệu lực, hoặc `min_score` quá cao | `curl localhost:6333/collections`; xem `meta.steps[0].detail.top_score` |
| `ModuleNotFoundError: sentence_transformers` | Provider thật cần extra `models` | `make dev-install` hoặc `LLM_PROVIDER=mock` |
| Câu trả lời cụt, `truncated: true` | Model thinking tiêu hết `max_tokens` | `LLM_REASONING_EFFORT=none` hoặc tăng `max_tokens` |
| 429 Gemini free tier | Quota theo ngày theo model | Đổi `LLM_MODEL` hoặc chạy Ollama |

---

[← 09 — API & giao diện](09-api-and-ui.md) · [Handbook](README.md) · [11 — Kiểm thử →](11-testing.md)
