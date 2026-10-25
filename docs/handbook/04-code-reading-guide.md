# 04 — Hướng dẫn đọc code

## Bản đồ repo

```
grounded-rag/
├── src/grounded_rag/            ← package chính (~2.800 dòng)
│   ├── service.py               ★ ĐỌC ĐẦU TIÊN: toàn bộ pipeline online
│   ├── types.py                 ★ kiểu dữ liệu domain: Chunk, Claim, Answer, …
│   ├── config.py                ★ Settings (env) + RunConfig (YAML)
│   ├── compute.py               pool luồng chạy model ngoài event loop
│   ├── api/
│   │   ├── main.py              app FastAPI, handler 503, mount UI và /metrics
│   │   ├── routes_chat.py       POST /chat, POST /chat/stream
│   │   ├── routes_admin.py      GET /healthz, POST /ingest, GET /configs
│   │   └── schemas.py           ChatRequest, IngestRequest, ConfigSummary
│   ├── retrieval/
│   │   ├── corrective.py        ★ retrieve(): tìm kiếm + vòng sửa lỗi + floor
│   │   ├── store.py             InMemoryStore, QdrantStore, lọc hiệu lực
│   │   ├── hybrid.py            Reciprocal Rank Fusion
│   │   ├── lexical.py           tokenizer tiếng Việt + BM25
│   │   ├── reranker.py          bge-reranker-v2-m3 | LexicalReranker
│   │   └── embedder.py          bge-m3 | HashEmbedder
│   ├── generation/
│   │   ├── llm_client.py        6 provider, retry/backoff, MeteredLLM
│   │   ├── prompts.py           ★ hợp đồng với model: system prompt, planner prompt
│   │   └── citation.py          trích/gỡ/kiểm tra mã [C1]
│   ├── guard/
│   │   ├── policy.py            ★ verify_claims, apply_policy, sinh lại
│   │   ├── nli_verifier.py      NLI, luật con số, premise views, cache LRU
│   │   └── claim_splitter.py    tách câu trả lời thành mệnh đề
│   ├── ingest/
│   │   ├── pipeline.py          ingest() + CLI
│   │   ├── chunkers.py          recursive_chunk, structural_chunk
│   │   └── loaders.py           đọc md/txt/pdf, front matter
│   └── observability/
│       ├── tracing.py           trace() span, collect_steps(), export Langfuse
│       └── metrics.py           Prometheus (no-op nếu chưa cài)
├── eval/                        ← bộ đánh giá (~1.000 dòng)
│   ├── run.py                   ★ chạy một cấu hình trên dataset → report JSON
│   ├── instrument.py            thước đo: ClauseIndex, judge_claims
│   ├── metrics.py               định nghĩa mọi metric, aggregate()
│   ├── report.py                gộp report → bảng markdown
│   ├── rejudge.py               chấm lại report cũ, không gọi LLM
│   ├── ragas_eval.py            RAGAS với LLM judge
│   ├── closed_book.py           ablation: cùng model, không tài liệu
│   └── dataset/                 questions.jsonl (100), questions.sample.jsonl (6), LABELING.md
├── scripts/                     công cụ một lần: corpus, τ, probe NLI, floor, chấm tay
├── tests/                       18 file, 135 test, chạy trên mock
├── app/web/                     UI một trang: index.html, app.js, styles.css
├── app/streamlit_demo.py        demo cũ (sẽ xóa)
├── configs/                     baseline · threshold · full · agentic
├── data/corpus/                 2 văn bản luật (commit)
├── data/sample_corpus/          trích 3 điều luật cho test/CI
├── reports/                     kết quả eval (một phần commit)
├── docs/                        tài liệu thiết kế, ADR, handbook này
├── Makefile · Dockerfile · docker-compose.yml · pyproject.toml · .env.example
└── .github/workflows/ci.yml
```

## Thứ tự đọc khuyến nghị

### Vòng 1 — hình dạng hệ thống (45 phút)

1. **`src/grounded_rag/types.py`** — đọc hết. Mọi thứ khác truyền qua lại các
   kiểu này. Chú ý `Chunk.ref`, `Chunk.in_force`, bốn `AnswerStatus`, bốn
   `AbstainReason`, `ABSTAIN_TEXT`.
2. **`src/grounded_rag/config.py`** — `Settings` và `RunConfig`. Mở kèm
   `configs/full.yaml` và `configs/agentic.yaml`.
3. **`src/grounded_rag/service.py`** — đọc từ trên xuống, ~170 dòng.
   `answer_question()` bọc đo lường; `_answer()` là pipeline. Đây là xương sống:
   mọi module khác là thứ hàm này gọi.
4. **`src/grounded_rag/api/routes_chat.py`** — để thấy request vào service ra sao.

Sau vòng này bạn trả lời được: một câu hỏi đi qua những bước nào, khi nào hệ
thống từ chối, và vì sao từ chối.

### Vòng 2 — từng thành phần (2–3 giờ)

Theo đúng thứ tự `service._answer()` gọi:

| # | File | Đọc gì | Câu hỏi nên trả lời được |
|---|---|---|---|
| 5 | `retrieval/corrective.py` | `search`, `retrieve`, `merge`, `parse_plan` | Floor áp ở đâu? Khi nào planner chạy? Vì sao giữ lại 1 lời gọi LLM? |
| 6 | `retrieval/store.py` | `QdrantStore.upsert`, `_query`, `_in_force_filter`, `get_store` | Vì sao mỗi chunker một collection? Ingest lại có nhân đôi dữ liệu không? |
| 7 | `retrieval/lexical.py`, `hybrid.py` | `tokenize`, `sparse_doc_vector`, `reciprocal_rank_fusion` | BM25 trong Qdrant tính IDF ở đâu? |
| 8 | `retrieval/reranker.py` | `BGEReranker.rerank` | Vì sao tự tính sigmoid? |
| 9 | `generation/prompts.py` | `SYSTEM_PROMPT`, `build_user_prompt` | Sáu quy tắc của prompt là gì, cái nào guard kiểm lại? |
| 10 | `generation/llm_client.py` | `OpenAICompatClient`, `_post_json`, `_retry_wait`, `MeteredLLM`, `MockClient` | Lỗi nào được thử lại? 429 chờ bao lâu? |
| 11 | `generation/citation.py` | cả file (34 dòng) | — |
| 12 | `guard/claim_splitter.py` | `split_claims`, `_PROTECTED`, `_BRACKET` | Vì sao "Điều 35." không kết thúc câu? |
| 13 | `guard/nli_verifier.py` | `numbers_supported`, `premise_views`, `NLIVerifier.entailment` | Luật con số chặn gì mà NLI không chặn? |
| 14 | `guard/policy.py` | `is_abstention`, `verify_claims`, `_recite`, `apply_policy`, `should_regenerate` | Khi nào `partial`, khi nào `abstained`? |
| 15 | `compute.py` | cả file | Vì sao không dùng `asyncio.to_thread`? |
| 16 | `observability/tracing.py` | `trace`, `collect_steps` | `meta.steps` được điền thế nào? |

### Vòng 3 — offline và đánh giá (2 giờ)

| # | File | Đọc gì |
|---|---|---|
| 17 | `ingest/loaders.py`, `chunkers.py`, `pipeline.py` | `structural_chunk`, `_parse_articles`, `_pieces` |
| 18 | `eval/dataset/LABELING.md`, vài dòng `questions.jsonl` | Bốn loại câu hỏi, định dạng `gold_chunks` |
| 19 | `eval/metrics.py` | `hallucinated`, `covers`, `aggregate` (docstring đầu file là quy tắc đo) |
| 20 | `eval/instrument.py` | `ClauseIndex.premises`, `judge_claims` |
| 21 | `eval/run.py` | `run()`, `--gate`, `--split` |
| 22 | Một report thật | `reports/2026-10-12-gemini/full.json` — xem một `cases[i]` đầy đủ |

### Vòng 4 — test như tài liệu sống

`tests/test_service_smoke.py` và `tests/test_policy.py` có tên test dạng câu
("the models own refusal is an abstention not a hallucination") — đọc tên test
là đọc đặc tả hành vi. Xem [11](11-testing.md).

## Từng file làm gì

### Lõi

| File | Trách nhiệm | Hàm/kiểu chính | Gọi tới | Được gọi bởi |
|---|---|---|---|---|
| `types.py` | Kiểu domain | `DocMeta`, `Chunk`, `RetrievedChunk`, `Claim`, `Verdict`, `AnswerStatus`, `AbstainReason`, `Step`, `AnswerMeta`, `Answer`, `ABSTAIN_TEXT` | pydantic | mọi nơi |
| `config.py` | Cấu hình | `Settings`, `settings` (singleton), `RunConfig.from_yaml`, `RetrievalConfig`, `CorrectiveConfig`, `GenerationConfig`, `GuardConfig` | pydantic-settings, yaml | mọi nơi |
| `service.py` | Pipeline online | `answer_question`, `_answer`, `_declined`, `_drop_bogus` | retrieval, generation, guard, observability, compute | `api/routes_chat`, `eval/run`, `eval/closed_book` |
| `compute.py` | Chạy model ngoài event loop | `mark_arrival`, `run_model`, `_OldestFirstPool` | threading, queue | `service`, `corrective`, `routes_admin` |

### API

| File | Trách nhiệm | Ghi chú |
|---|---|---|
| `api/main.py` | Tạo app, gắn router, handler `LLMUnavailable` → 503, mount `/static` + `/` (UI), mount `/metrics` nếu có prometheus-client, đóng HTTP pool ở `lifespan` | `WEB_DIR` tìm `app/web` theo đường dẫn repo, dự phòng `./app/web` |
| `api/routes_chat.py` | `/chat`, `/chat/stream`, `load_config(name)` | `CONFIG_DIR = Path("configs")` — **đường dẫn tương đối**, server phải chạy từ gốc repo |
| `api/routes_admin.py` | `/healthz`, `/ingest` (`require_admin`, `corpus_dir`), `/configs` | So sánh key bằng `hmac.compare_digest`; chặn `..` và symlink bằng `resolve()` + `is_relative_to` |
| `api/schemas.py` | Schema request/response | `question` 1–1000 ký tự; `config` khớp `^[A-Za-z0-9_-]+$`; `IngestRequest` cấm trường lạ |

### Retrieval

| File | Trách nhiệm | Ghi chú |
|---|---|---|
| `retrieval/corrective.py` | `search` (một truy vấn qua hybrid + rerank), `retrieve` (vòng sửa lỗi + floor), `plan_queries`, `parse_plan`, `merge` | Điểm trả về là điểm **rerank** — thang mà `min_score` dùng |
| `retrieval/store.py` | Protocol `VectorStore`; `InMemoryStore`; `QdrantStore` (named vectors `dense` + `sparse`); `_in_force_filter`; `get_store` | Collection = `{QDRANT_COLLECTION}_{chunker}` |
| `retrieval/hybrid.py` | `reciprocal_rank_fusion(runs, k=60)` | 21 dòng |
| `retrieval/lexical.py` | `tokenize`, `BM25Index`, `sparse_doc_vector`, `sparse_query_vector` | Chỉ số token = `crc32` để ổn định giữa các tiến trình |
| `retrieval/reranker.py` | `BGEReranker` (batch 16, max_length 512, sigmoid), `LexicalReranker` | — |
| `retrieval/embedder.py` | `BGEEmbedder` (chuẩn hóa L2), `HashEmbedder` (1024 chiều) | — |

### Generation

| File | Trách nhiệm | Ghi chú |
|---|---|---|
| `generation/llm_client.py` | `LLMClient` protocol; `MockClient`; `OpenAICompatClient`; `AnthropicClient`; `_ConnectionPool`; `MeteredLLM`; `_post_json`; `_retry_wait`; `get_llm_client`; `LLMUnavailable`; `BudgetExceeded` | Không dùng SDK. Thử lại 408/429/5xx |
| `generation/prompts.py` | `SYSTEM_PROMPT`, `ANSWER_REMINDER`, `build_user_prompt`, `planner_system_prompt`, `build_planner_prompt` | Prompt viết tiếng Việt; sửa prompt = chạy lại eval |
| `generation/citation.py` | `extract_citations`, `strip_citations`, `invalid_citations`, `label_for` | Regex `\[(C\d+)\]` |

### Guard

| File | Trách nhiệm | Ghi chú |
|---|---|---|
| `guard/claim_splitter.py` | `split_claims` → `list[Claim]` | Bảo vệ "Điều 35.", "Khoản 1."; dời `[C1]` đặt sau dấu chấm vào trong câu; bỏ ký hiệu danh sách, tiền tố "Câu trả lời:", dòng dẫn nhập kết thúc bằng ":" |
| `guard/nli_verifier.py` | `Verifier` protocol, `MockVerifier`, `NLIVerifier`, `numbers`, `numbers_supported`, `premise_views`, `get_verifier` | Cache LRU khóa bằng `sha256(premise‖hypothesis)`, có lock |
| `guard/policy.py` | `is_abstention`, `verify_claims`, `_cited_premises`, `_recite`, `unsupported`, `apply_policy`, `should_regenerate`, `regeneration_feedback` | Phản hồi sinh lại viết tiếng Việt, liệt kê đích danh mệnh đề sai |

### Ingest

| File | Trách nhiệm | Ghi chú |
|---|---|---|
| `ingest/loaders.py` | `load_file`, `split_front_matter`, `iter_corpus`, `Document` | `.md`, `.txt`, `.pdf` (PDF dùng file `<tên>.meta.yaml` đặt cạnh) |
| `ingest/chunkers.py` | `recursive_chunk` (1200 ký tự, overlap 150), `structural_chunk` (≤1800 ký tự), `get_chunker` | Structural tự lùi về recursive nếu không tìm thấy Điều nào |
| `ingest/pipeline.py` | `ingest(source, config, recreate=False)`, CLI `--source --config --recreate` | Trả `{files, chunks, written}` |

### Observability

| File | Trách nhiệm |
|---|---|
| `observability/tracing.py` | `collect_steps()` (contextvar giữ list `Step`), `trace(name, **attrs)` (đo giờ, ghi Step, đẩy Prometheus, log debug), `export()` sang Langfuse (best effort) |
| `observability/metrics.py` | `grounded_rag_step_seconds{step}`, `grounded_rag_answers_total{config,status,reason}`, `grounded_rag_llm_tokens_total{config}`, `grounded_rag_llm_calls_total{config}` |

### Eval và scripts

Xem bảng đầy đủ ở [08](08-evaluation.md).

## Mẹo đọc code

- **Docstring và comment giải thích "vì sao"**, thường kèm lỗi thật đã gặp
  (ví dụ "lao động1." ở `recursive_chunk`, "[60 ngày]" ở `claim_splitter`). Đọc
  chúng trước khi đọc thân hàm.
- **Tìm theo tên trạng thái**: `grep -rn "AbstainReason.GUARD" src` cho thấy mọi
  chỗ guard từ chối.
- **Chạy một câu bằng mock để xem `meta.steps`**:
  `LLM_PROVIDER=mock ADMIN_API_KEY=dev make run`, rồi `ADMIN_API_KEY=dev make seed`,
  rồi mở `http://localhost:8000/?q=Nghỉ việc phải báo trước bao nhiêu ngày?`.
- **Đặt breakpoint trong test**: `pytest tests/test_service_smoke.py -k agentic -s`
  chạy toàn pipeline trong vài giây, không cần model.
- **Đọc report thật** để thấy dữ liệu chảy qua mỗi bước:
  `python -c "import json; c=json.load(open('reports/2026-10-12-gemini/full.json'))['cases'][0]; print(json.dumps(c, ensure_ascii=False, indent=1)[:3000])"`.

---

[← 03 — Kiến trúc](03-architecture.md) · [Handbook](README.md) · [05 — Pipeline truy vấn →](05-query-pipeline.md)
