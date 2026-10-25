# 05 — Pipeline truy vấn, từng bước

Theo một request `POST /chat` từ lúc vào tới lúc ra. Ví dụ xuyên suốt:

```json
{ "question": "Nghỉ việc phải báo trước bao nhiêu ngày?", "config": "full" }
```

## Bước 0 — HTTP vào

`api/routes_chat.py::chat`

1. FastAPI validate body bằng `ChatRequest`: `question` 1–1000 ký tự, `config`
   khớp `^[A-Za-z0-9_-]+$` (chỉ là tên file, không phải đường dẫn), `as_of`
   là ngày hoặc `null`. Sai → **422**.
2. `load_config("full")` đọc `configs/full.yaml` thành `RunConfig`. File không
   tồn tại → **404**. Config được đọc lại **mỗi request** (sửa YAML có hiệu lực
   ngay, không cần restart).
3. Gọi `service.answer_question(question, config, as_of=req.as_of)`.

## Bước 1 — khởi tạo đo lường

`service.py::answer_question`

```python
started = time.perf_counter()
mark_arrival()                                   # ưu tiên trong pool model (compute.py)
llm = MeteredLLM(get_llm_client(), config.max_llm_calls)   # ngân sách: 4 lời gọi
with collect_steps() as steps:                   # mọi trace() bên trong ghi vào đây
    out = await _answer(question, config, llm, as_of or date.today())
```

Sau khi `_answer` trả về, hàm điền `meta.latency_ms`, `tokens`, `llm_calls`,
`cost_usd`, `config`, `steps`, rồi đẩy Prometheus (`metrics.observe_answer`) và
Langfuse (`export_trace`, bỏ qua nếu chưa cấu hình).

## Bước 2 — truy xuất

`retrieval/corrective.py::retrieve` → `search`

### 2a. Một lần tìm (`search`)

```
store = get_store("structural")                   # collection grounded_rag_structural
dense  = store.dense_search(q, top_k=20, as_of)   # bge-m3, cosine, lọc hiệu lực trong Qdrant
sparse = store.sparse_search(q, top_k=20, as_of)  # BM25 (nếu hybrid: true)
fused  = reciprocal_rank_fusion([dense, sparse])[:20]     # rerank_candidates
hits   = reranker.rerank(q, fused, top_n=5)               # rerank_to; điểm sigmoid 0–1
```

Chạy qua `run_model` (pool luồng), được bọc trong span `retrieve` ghi `query`
và `top_score`.

### 2b. Vòng sửa lỗi (chỉ khi `corrective.enabled`, tức cấu hình `agentic`)

```
lặp tối đa max_rounds (=1):
    top_score ≥ confident_score (0.60)   → dừng, giữ kết quả
    llm.left < 2                          → dừng (giữ 1 lời gọi cho câu trả lời)
    plan = plan_queries(...)              # 1 lời gọi LLM, span "plan"
    plan.in_domain == False               → trả Retrieval(out_of_domain=True)
    truy vấn mới (khác những gì đã thử)   → search từng cái, span "retrieve"
    không có truy vấn mới                 → dừng
```

Planner phải trả JSON `{"in_domain": true, "queries": [...]}`. `parse_plan`
chịu lỗi: JSON hỏng hay thiếu trường đều thành "không có truy vấn mới", không
bao giờ ném lỗi.

### 2c. Gộp và floor (`merge`)

Mọi danh sách kết quả (một nếu không có vòng sửa lỗi) được:

1. lọc bỏ chunk có điểm `< min_score` (0.30 ở `threshold`/`full`/`agentic`, 0
   ở `baseline`);
2. gộp **round-robin** theo thứ hạng để mỗi truy vấn con đều có chỗ;
3. bỏ trùng theo `chunk_id`, giữ điểm cao nhất;
4. cắt còn `rerank_to` (5).

### Kết quả bước 2

| `Retrieval` | Điều xảy ra tiếp |
|---|---|
| `out_of_domain=True` | → `no_context`, `abstain_reason: out_of_domain`, **0 lời gọi sinh** |
| `hits` rỗng | → `no_context`, `abstain_reason: retrieval_floor` (lớp phòng thủ 1) |
| có `hits` | → bước 3 |

## Bước 3 — dựng prompt

`service._answer` + `generation/prompts.py::build_user_prompt`

Mỗi hit thành `RetrievedChunk(label="C1".."C5")`. User prompt:

```
TÀI LIỆU:
[C1]
Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động của người lao động
1. Người lao động có quyền ... phải báo trước ít nhất 45 ngày ...

[C2]
...

CÂU HỎI: Nghỉ việc phải báo trước bao nhiêu ngày?

Trả lời bằng câu văn đầy đủ, cuối mỗi câu ghi mã [C1], [C2]...

TRẢ LỜI:
```

Header của mỗi đoạn **chỉ có nhãn** (`[C1]`): khi header có cả "Điều 105,
Khoản 1", model nhỏ chép nó thành mã trích dẫn. Dòng nhắc trước `TRẢ LỜI:` tăng
tỉ lệ qwen2.5:3b giữ đúng định dạng từ 1/4 lên 3/4.

System prompt (`SYSTEM_PROMPT`) có sáu quy tắc: chỉ dùng tài liệu; có thông tin
thì bắt buộc trả lời; chép nguyên văn con số (không thay con số bằng `[C1]`);
mã trích dẫn ở cuối mỗi câu, không dùng số điều làm mã; không suy diễn; không đủ
thông tin thì viết **đúng** câu `ABSTAIN_TEXT` = "Không tìm thấy thông tin này
trong tài liệu."; tối đa 5 câu.

## Bước 4 — sinh (vòng `while True`)

```python
res = await llm.complete(SYSTEM_PROMPT, user, temperature=0.0, max_tokens=512)
```

- Span `generate` ghi `attempt`, `tokens`, `truncated`.
- `truncated=True` (provider dừng ở `max_tokens`, hay gặp với model "thinking")
  → log warning; eval đếm `truncated_generations`.
- Văn bản thô chỉ đi vào log debug, **không bao giờ** vào response.

### 4a. Gỡ trích dẫn bịa (lớp phòng thủ 3)

`invalid_citations(text, ["C1".."C5"])` → các mã như `[C9]` bị xóa khỏi văn bản
(`_drop_bogus`). Không cần chạy model nào.

### 4b. Model tự từ chối? (lớp phòng thủ 2)

`policy.is_abstention(text)`: văn bản (bỏ trích dẫn, bỏ dấu câu, viết thường)
**bằng** câu từ chối, hoặc **chứa** câu từ chối mà không có trích dẫn nào.

| Lượt | Đã có mệnh đề `supported` từ lượt trước? | Kết quả |
|---|---|---|
| 1 | — | `abstained`, `abstain_reason: model`, không sinh lại |
| ≥2 | có | thoát vòng, trả lời bằng các mệnh đề đã kiểm chứng (`partial`) |
| ≥2 | không | `abstained`, `abstain_reason: guard`, `claims` = các mệnh đề guard đã từ chối |

### 4c. Guard tắt (`baseline`, `threshold`)

`claims = split_claims(text)` (verdict `null`), thoát vòng. Câu trả lời tới người
dùng **đúng như model viết** — baseline không được hưởng chút lợi nào của guard.

### 4d. Guard bật (`full`, `agentic`) — lớp phòng thủ 4

```python
claims = await run_model(verify_claims, text, sources, get_verifier(), τ=0.50)
```

Span `verify` ghi `claims` và `unsupported`. Chi tiết ở [07](07-guard.md):
tách mệnh đề → mỗi mệnh đề: không trích dẫn → `uncited`; có trích dẫn → điểm
NLI trên premise ghép từ các đoạn được trích (luật con số trước); dưới τ thì thử
các đoạn khác (`_recite`) → `supported` / `unsupported`.

### 4e. Sinh lại?

`should_regenerate(claims, guard, attempts)` đúng khi guard bật, `attempts ≤
max_regenerations` (1), và có mệnh đề không `supported` (hoặc không có mệnh đề
nào). Thêm điều kiện ngoài: `llm.left ≥ 1`.

Nếu sinh lại: user prompt = prompt gốc + `regeneration_feedback(claims)`:

```
[YÊU CẦU SỬA - không chép lại đoạn này]
Câu trả lời trước có những mệnh đề KHÔNG được tài liệu chứng minh:
- <mệnh đề sai 1>
Hãy viết lại, chỉ dùng thông tin có trong tài liệu được cung cấp. Nếu tài liệu
không đủ thông tin, trả lời đúng một câu: "Không tìm thấy thông tin này trong tài liệu."
```

Quay lại đầu bước 4. Nhiều nhất 2 lượt sinh.

## Bước 5 — chính sách cuối

`guard/policy.py::apply_policy`

| Guard | Mệnh đề `supported` | Mệnh đề không `supported` | `on_unsupported` | `status` | `answer` |
|---|---|---|---|---|---|
| tắt | — | — | — | `answered` (rỗng → `abstained`) | văn bản model, nguyên vẹn |
| bật | 0 | bất kỳ | — | `abstained` (`reason: guard`) | `ABSTAIN_TEXT` |
| bật | ≥1 | 0 | — | `answered` | các mệnh đề ghép lại kèm `[Cx]` |
| bật | ≥1 | ≥1 | `drop_claim` | `partial` | chỉ các mệnh đề `supported` |
| bật | ≥1 | ≥1 | `abstain_all` | `abstained` (`reason: guard`) | `ABSTAIN_TEXT` |

`claims` trong response luôn chứa **mọi** mệnh đề, kể cả mệnh đề bị bỏ, kèm
`entailment` và `verdict` — UI hiển thị chúng gạch ngang.

## Bước 6 — HTTP ra

`Answer` được serialize thành JSON (200). Ví dụ rút gọn:

```json
{
  "answer": "Người lao động phải báo trước ít nhất 45 ngày [C1].",
  "status": "answered",
  "claims": [{"text": "Người lao động phải báo trước ít nhất 45 ngày.", "citations": ["C1"],
              "entailment": 0.99, "verdict": "supported", "cited_as": null}],
  "sources": [{"label": "C1", "score": 0.87, "chunk": {"ref": "bo_luat_lao_dong_2019:Điều 35:1", "...": "..."}}],
  "meta": {"regenerated": false, "latency_ms": 24100, "tokens": 612, "llm_calls": 1,
           "cost_usd": 0.0, "config": "full", "abstain_reason": null,
           "steps": [{"name": "retrieve", "ms": 9800, "detail": {"query": "...", "top_score": 0.87}},
                     {"name": "generate", "ms": 12300, "detail": {"attempt": 1, "tokens": 612, "truncated": false}},
                     {"name": "verify", "ms": 1900, "detail": {"claims": 1, "unsupported": 0}}]}
}
```

Provider lỗi sau khi thử lại → `LLMUnavailable` → handler trong `api/main.py`
trả **503**.

## Bảng tổng hợp mọi lối ra

| Lối ra | `status` | `abstain_reason` | Lời gọi LLM | Ở đâu trong code |
|---|---|---|---|---|
| Planner: không phải câu hỏi pháp luật | `no_context` | `out_of_domain` | 1 | `service._answer` sau `retrieve` |
| Không chunk nào vượt floor | `no_context` | `retrieval_floor` | 0 (hoặc 1 nếu planner đã chạy) | `service._answer` |
| Model từ chối ngay lượt đầu | `abstained` | `model` | 1 | nhánh `is_abstention` |
| Model từ chối sau khi bị guard sửa, không có gì đã kiểm chứng | `abstained` | `guard` | 2 | nhánh `is_abstention` |
| Model từ chối sau khi bị guard sửa, đã có mệnh đề tốt | `partial` | — | 2 | `break` → `apply_policy` |
| Guard loại hết mệnh đề | `abstained` | `guard` | 1–2 | `apply_policy` |
| Guard loại một phần | `partial` | — | 1–2 | `apply_policy` |
| Mọi mệnh đề đạt | `answered` | — | 1–2 | `apply_policy` |
| Guard tắt | `answered` | — | 1 | `_answer` (4c) |

## Ngân sách lời gọi LLM

`max_llm_calls` (mặc định 4, `agentic` ghi rõ 4): planner 1 + sinh 1 + sinh lại
1 + 1 dự phòng. Ba chỗ kiểm tra:

1. Vòng corrective dừng khi `llm.left < 2`.
2. Sinh lại chỉ khi `llm.left ≥ 1`.
3. `MeteredLLM.complete` ném `BudgetExceeded` nếu vượt (lẽ ra không bao giờ).

## Streaming (`POST /chat/stream`)

Gọi đúng `answer_question` như trên, **chờ xong toàn bộ** (kể cả kiểm chứng),
rồi mới phát SSE:

```
event: claim   data: {mệnh đề 1}
event: claim   data: {mệnh đề 2}
event: done    data: {"status": ..., "answer": ..., "meta": {...}}
```

Lỗi provider → `event: error`. Lý do kiểm chứng trước khi stream:
[ADR-0003](../adr/0003-verify-before-stream.md). Hiện chưa có sự kiện tiến độ
trong lúc chờ (kế hoạch S4 trong [../13-sprint-plan.md](../13-sprint-plan.md)).

## Độ trễ thực tế (CPU laptop, Gemini free tier)

| Bước | Thời gian | Ghi chú |
|---|---|---|
| `retrieve` | 8–11 s | Gần như toàn bộ là cross-encoder rerank 20 ứng viên |
| `generate` | ~12 s/lượt | Gemini free tier |
| `verify` | 1–3 s | NLI trên nhiều premise view; regenerate thì gấp đôi |
| p50 tổng | ~24 s | mọi cấu hình |
| p95 `full` | 69 s | câu bị guard bắt: verify + sinh lại + verify lần 2 |

---

[← 04 — Đọc code](04-code-reading-guide.md) · [Handbook](README.md) · [06 — Ingest & retrieval →](06-ingest-and-retrieval.md)
