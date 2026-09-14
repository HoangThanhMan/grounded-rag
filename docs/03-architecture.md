# 03 — Kiến trúc

## Sơ đồ tổng thể

```
OFFLINE — ingest (idempotent)

  data/corpus/*.md|pdf        front matter: số hiệu, cơ quan ban hành, ngày hiệu lực
        │
  loaders.py ─► chunkers.py ──────────► embedder.py  (bge-m3, dense)
                recursive | structural   lexical.py   (BM25, sparse)
                (chunk mang tiêu đề Điều)       │
                                                ▼
                                store.py — Qdrant, mỗi chunker một collection

ONLINE — query

  question, as_of
        │
  corrective.search ─ dense  ┐
   (bỏ văn bản chưa có hoặc   ├─ RRF ─► reranker (cross-encoder) ─► điểm 0–1
    đã hết hiệu lực)          │
                    sparse   ┘
        │
        ├─ [agentic] điểm < confident_score → planner (1 lời gọi LLM):
        │            viết lại thuật ngữ / tách ý → tìm lại → gộp round-robin
        │
        ├─ không gì vượt min_score ───────────────────► NO_CONTEXT (floor)
        ▼
  top-5, nhãn C1..C5 ─► prompts.py ─► llm_client.py
        │
        ├─ model trả đúng câu từ chối ────────────────► ABSTAINED (model)
        ▼
  citation.py       mã trích dẫn không tồn tại → gỡ bỏ
  claim_splitter    tách mệnh đề (câu, dòng, gạch đầu dòng)
  nli_verifier      P(entailment) giữa mệnh đề và đoạn được trích
  policy.py         trả lời | sinh lại 1 lần | bỏ mệnh đề | từ chối
        ▼
  Answer (JSON | SSE) + meta: steps, llm_calls, tokens, cost, abstain_reason
```

`tracing.py` đo giờ từng bước (`retrieve` · `plan` · `generate` · `verify`), trả
về trong `meta.steps` và đẩy lên Prometheus (`GET /metrics`).

## Điểm vào để đọc code

`src/grounded_rag/service.py` — hàm `answer_question()` là toàn bộ pipeline
online, đọc từ trên xuống là hiểu hệ thống. Phần truy xuất (kể cả vòng sửa lỗi)
nằm trong `retrieval/corrective.py::retrieve()`. Mọi module khác là thành phần
mà hai hàm này gọi.

## Bốn lớp phòng thủ chống bịa

Xếp theo thứ tự rẻ → đắt. Cái rẻ chặn trước để cái đắt ít việc.

| Lớp | Cơ chế | Chi phí | Chặn được gì |
|---|---|---|---|
| 1 | Ngưỡng retrieval (`min_score`) | ~0, chưa gọi LLM | Câu hỏi hoàn toàn ngoài phạm vi |
| 2 | Prompt cho phép model từ chối | 0, nằm trong lời gọi sinh | Model tự nhận ra tài liệu không đủ |
| 3 | Validate mã trích dẫn | ~0 | Model bịa mã `[C9]` không tồn tại |
| 4 | NLI guard | 1 lần forward/mệnh đề | Mệnh đề nghe hợp lý nhưng tài liệu không nói |

Lớp 4 là phần lõi. Lớp 1–3 tồn tại vì gần như miễn phí. Eval báo cáo mỗi lớp
chặn được bao nhiêu câu không-trả-lời-được (`correct_abstention_by_layer`), để
biết lớp đắt nhất có thật sự làm việc hay chỉ đứng sau lưng lớp rẻ.

## Retrieval

- **Dense:** bge-m3, đa ngữ, mạnh tiếng Việt.
- **Sparse:** BM25 trên âm tiết + bigram âm tiết. Trong Qdrant là sparse vector
  với `Modifier.IDF`. [ADR-0006](adr/0006-bm25-sparse-retrieval.md)
- **Hợp nhất:** Reciprocal Rank Fusion, `k=60`, cắt ở `rerank_candidates`.
- **Rerank:** bge-reranker-v2-m3, cross-encoder, điểm = sigmoid(logit) trong
  [0, 1], giữ `rerank_to` (5).
- **Ngưỡng:** điểm rerank cao nhất < `min_score` → `NO_CONTEXT`, không gọi LLM.
- **Hiệu lực:** `as_of` (mặc định hôm nay) loại chunk của văn bản chưa có hoặc
  đã hết hiệu lực. Lọc ngay trong Qdrant, trước khi xếp hạng.
- **Một index mỗi chunker:** `baseline` (recursive) và `full` (structural)
  không bao giờ truy xuất chunk của nhau.

## Truy xuất sửa lỗi (cấu hình `agentic`)

Khi điểm rerank cao nhất dưới `confident_score`, một lời gọi LLM (planner) trả
JSON: câu hỏi còn thuộc pháp luật không, và 1–3 truy vấn viết lại hoặc tách ý.
Mỗi truy vấn mới được tìm và rerank riêng, rồi gộp round-robin để ý nào cũng có
chỗ trong ngữ cảnh. Vòng lặp có trần cứng. Chi tiết và lý do không dùng
framework: [ADR-0005](adr/0005-corrective-retrieval-loop.md).

## Generation

Hợp đồng nằm trong `prompts.py::SYSTEM_PROMPT`. Bốn ràng buộc: chỉ dùng tài
liệu, mỗi câu phải có mã trích dẫn, không suy diễn, không đủ thông tin thì trả
đúng một câu từ chối.

Câu từ chối đó được nhận diện (`policy.is_abstention`). Đó là một lần từ chối
cần báo cáo, không phải một mệnh đề cần kiểm chứng, và không kích hoạt sinh lại.

**Prompt và guard phải đi cùng nhau.** Nới lỏng prompt thì tỉ lệ guard chặn sẽ
tăng. Sửa một cái, chạy lại eval cả bốn cấu hình.

## Lớp trừu tượng provider

`llm_client.py` định nghĩa protocol `LLMClient` với `complete()` và `stream()`.
Đổi provider là đổi biến môi trường, không sửa code:

| `LLM_PROVIDER` | Client | Ghi chú |
|---|---|---|
| `mock` | `MockClient` | Test, CI, clone về chạy ngay |
| `ollama` | `OpenAICompatClient` | `{OLLAMA_BASE_URL}/v1` |
| `vllm` | `OpenAICompatClient` | Model mở, service `vllm` trong compose ([ADR-0007](adr/0007-no-generator-fine-tuning.md)) |
| `openai` | `OpenAICompatClient` | Mọi server nói giao thức OpenAI |
| `gemini` | `OpenAICompatClient` | Endpoint tương thích OpenAI của Gemini |
| `anthropic` | `AnthropicClient` | Messages API |

Cả hai client gọi HTTP thẳng qua httpx, không dùng SDK, nên giao thức nhìn thấy
được. Lỗi tạm thời (timeout, 429, 5xx) được thử lại với backoff; hết lượt thử
thì ra `LLMUnavailable`, API trả **503**. Từ chối trả lời vẫn là 200. Tên
provider sai là lỗi khởi động, không lặng lẽ rơi về mock.

`MeteredLLM` bọc client cho từng câu hỏi: giữ trần `max_llm_calls`, cộng token
và chi phí (`LLM_*_USD_PER_MTOK`) của mọi lời gọi — planner, sinh, sinh lại.

`mock` không phải đồ chơi: nó là thứ khiến toàn bộ test suite và CI chạy được
mà không cần API key. Reranker của mock (`LexicalReranker`) cho điểm cùng thang
0–1 với cross-encoder thật, nên floor hoạt động đúng nghĩa ngay trong mock.

## Quan sát (observability)

- **`meta.steps`:** mỗi câu trả lời mang theo trace của chính nó — bước, thời
  gian, điểm retrieval, truy vấn planner, token. Eval lưu lại nguyên vẹn, nên
  chi phí của vòng sửa lỗi nhìn thấy được theo từng câu.
- **Prometheus `GET /metrics`** (extra `obs`): `grounded_rag_step_seconds{step}`,
  `grounded_rag_answers_total{config,status,reason}`, `grounded_rag_llm_tokens_total`,
  `grounded_rag_llm_calls_total`.
- **Langfuse:** service đã có trong compose; đẩy trace lên vẫn là TODO tuần 3.

## Chọn công nghệ và lý do

| Thành phần | Chọn | Vì sao |
|---|---|---|
| API | FastAPI | Async, SSE sẵn, pydantic validation |
| Vector store | Qdrant | Named vectors dense+sparse, IDF phía server, lọc payload ([ADR-0002](adr/0002-qdrant-as-vector-store.md)) |
| Embedding | bge-m3 | Đa ngữ, mạnh tiếng Việt |
| Sparse | BM25 | Khớp token pháp lý chính xác, không cần model ([ADR-0006](adr/0006-bm25-sparse-retrieval.md)) |
| Rerank | bge-reranker-v2-m3 | Cross-encoder đa ngữ |
| Guard | mDeBERTa-v3 XNLI | Đa ngữ, chạy được CPU, tất định ([ADR-0001](adr/0001-nli-over-llm-judge.md)) |
| Model mở | vLLM / Ollama | Giao thức OpenAI, trọng số lượng tử hoá sẵn ([ADR-0007](adr/0007-no-generator-fine-tuning.md)) |
| Metrics | Prometheus | Chuẩn, một endpoint |
| Tracing | Langfuse | Chuyên cho LLM: token, cost, score |
| Demo | Streamlit | Đủ để hiện verdict và trace, không tốn thời gian |

## Cái đã cân nhắc rồi loại

- **LangChain / LlamaIndex / LangGraph** — bỏ. Pipeline chỉ có vài bước, vòng
  lặp duy nhất có hai nhánh, và bước quan trọng nhất (guard) là code tự viết.
  Framework làm khó đọc hơn và làm mất khả năng giải thích từng bước khi phỏng
  vấn. [ADR-0005](adr/0005-corrective-retrieval-loop.md)
- **Agent ReAct tự do, HyDE** — [ADR-0005](adr/0005-corrective-retrieval-loop.md).
- **Fine-tune model sinh (Unsloth, QLoRA, QAT)** — [ADR-0007](adr/0007-no-generator-fine-tuning.md).
- **Sparse vector bge-m3** — [ADR-0006](adr/0006-bm25-sparse-retrieval.md).
- **LLM-as-judge cho guard** — [ADR-0001](adr/0001-nli-over-llm-judge.md). Vẫn
  dùng LLM judge ở một chỗ: RAGAS trong eval, làm đối chứng.
- **Stream trước, kiểm chứng sau** — [ADR-0003](adr/0003-verify-before-stream.md).
