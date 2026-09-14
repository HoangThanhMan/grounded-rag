# 05 — Thiết kế API

Base URL: `http://localhost:8000` · OpenAPI: `/docs`

## `POST /chat`

```json
{ "question": "Nghỉ việc phải báo trước bao nhiêu ngày?", "config": "full", "as_of": "2026-09-11" }
```

`config` là tên file trong `configs/`: `baseline` | `threshold` | `full` |
`agentic`. Chỉ nhận tên (`^[A-Za-z0-9_-]+$`), không nhận đường dẫn. Cho phép
chọn cấu hình qua API là điều khiến việc so sánh các cấu hình trở thành một vòng
lặp, không phải nhiều lần sửa code.

`as_of` (không bắt buộc, mặc định hôm nay): đọc luật như vào ngày đó — văn bản
chưa có hoặc đã hết hiệu lực vào ngày ấy không được truy xuất.

### Phản hồi

```json
{
  "answer": "Người lao động phải báo trước ít nhất 45 ngày [C1].",
  "status": "answered",
  "claims": [
    {
      "text": "Người lao động phải báo trước ít nhất 45 ngày.",
      "citations": ["C1"],
      "entailment": 0.94,
      "verdict": "supported"
    }
  ],
  "sources": [
    {
      "chunk": { "chunk_id": "bo_luat_lao_dong_2019:9f2a...", "ref": "bo_luat_lao_dong_2019:Điều 35:1",
                 "article": "Điều 35", "clause": "Khoản 1", "chapter": "Chương III",
                 "effective_date": "2021-01-01", "text": "..." },
      "score": 0.87,
      "label": "C1"
    }
  ],
  "meta": {
    "regenerated": false, "latency_ms": 1840, "tokens": 612, "llm_calls": 1,
    "cost_usd": 0.0009, "config": "full", "abstain_reason": null,
    "steps": [
      { "name": "retrieve", "ms": 210, "detail": { "query": "...", "top_score": 0.87 } },
      { "name": "generate", "ms": 1350, "detail": { "attempt": 1, "tokens": 612 } },
      { "name": "verify",   "ms": 260, "detail": { "claims": 1, "unsupported": 0 } }
    ]
  }
}
```

`meta.steps` là trace của chính câu trả lời này. Với cấu hình `agentic` có thêm
bước `plan` (kèm các truy vấn planner đề xuất) và các bước `retrieve` sau đó.

### `status`

| Giá trị | Nghĩa |
|---|---|
| `answered` | Mọi mệnh đề đều được tài liệu chứng minh |
| `partial` | Một số mệnh đề bị guard loại, phần còn lại vẫn trả về |
| `abstained` | Model tự từ chối, hoặc guard loại hết |
| `no_context` | Dừng trước khi LLM viết câu trả lời nào |

### `meta.abstain_reason`

| Giá trị | Lớp nào đã dừng |
|---|---|
| `retrieval_floor` | Không chunk nào vượt `min_score` |
| `out_of_domain` | Planner (`agentic`) xác định đây không phải câu hỏi pháp luật |
| `model` | Model tự trả đúng câu từ chối mà prompt cho |
| `guard` | Guard loại hết mệnh đề, hoặc model từ chối sau khi guard nêu mệnh đề sai |

### `verdict` của từng mệnh đề

| Giá trị | Nghĩa |
|---|---|
| `supported` | `P(entailment) ≥ ngưỡng` |
| `unsupported` | Dưới ngưỡng |
| `uncited` | Mệnh đề không có mã trích dẫn nào — không thể chứng minh |
| `null` | Cấu hình tắt guard: mệnh đề được báo cáo nhưng không được kiểm chứng |

**Trả về cả `claims` kể cả khi tất cả đều `supported`.** Đây là điểm khác biệt
so với API RAG thông thường: người dùng thấy được *vì sao* nên tin câu trả lời,
không chỉ thấy câu trả lời.

## `POST /chat/stream`

Cùng request, trả SSE:

```
event: claim
data: {"text": "...", "citations": ["C1"], "entailment": 0.94, "verdict": "supported"}

event: done
data: {"status": "answered", "answer": "...", "meta": {...}}
```

Lưu ý: guard chạy **trước** khi gửi sự kiện đầu tiên. Đánh đổi này được ghi lại
trong [ADR-0003](adr/0003-verify-before-stream.md).

Provider LLM hỏng giữa chừng thì header đã gửi đi rồi, nên lỗi đi dưới dạng sự
kiện: `event: error` với `{"detail": "..."}`.

## `POST /ingest`

```json
{ "source": "data/corpus", "config": "full", "recreate": false }
→ { "files": 2, "chunks": 1847, "written": 1847 }
```

`config` quyết định chunker, và vì thế quyết định ghi vào index nào.
`written` < `chunks` nghĩa là phần lớn nội dung đã có trong chỉ mục — bằng
chứng ingest idempotent hoạt động. `recreate: true` xoá index của chunker đó
trước khi ghi.

## `GET /configs`

```json
[{ "name": "full", "guard_enabled": true, "entailment_threshold": 0.6,
   "corrective_enabled": false, "min_score": 0.3, "chunker": "structural" }]
```

Một dòng cho mỗi file trong `configs/`: cấu hình đó bật những lớp phòng vệ nào.
Giao diện demo dùng `entailment_threshold` để vẽ vạch ngưỡng trên thước
entailment, nên đổi ngưỡng trong YAML là giao diện đổi theo, không phải sửa hai
chỗ.

## `GET /` và `/static/*`

Giao diện demo một trang (`app/web/`), do chính API phục vụ: một tiến trình,
một origin, không cần CORS. `?q=...&config=...&as_of=...` hỏi luôn khi mở trang.

## `GET /healthz`

```json
{ "status": "ok", "provider": "mock" }
```

## `GET /metrics`

Định dạng Prometheus, có khi cài extra `obs`. Độ trễ từng bước, số câu trả lời
theo `config`/`status`/`reason`, token và số lời gọi LLM.

## Lỗi

| Mã | Khi nào |
|---|---|
| 404 | `config` không tồn tại trong `configs/` |
| 422 | `question` rỗng hoặc quá 1000 ký tự; `config` không phải tên hợp lệ; `as_of` sai định dạng |
| 503 | Provider LLM không phản hồi sau khi đã thử lại (`LLMUnavailable`) |

**Không có mã lỗi cho "không trả lời được".** Từ chối trả lời là một kết quả
hợp lệ, trả về 200 với `status: abstained` — không phải lỗi hệ thống.
