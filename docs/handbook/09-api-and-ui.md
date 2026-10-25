# 09 — API & giao diện

Base URL mặc định `http://localhost:8000`. OpenAPI tự sinh tại `/docs` (Swagger)
và `/openapi.json`. Mọi route nằm ở gốc, **chưa có tiền tố `/v1`** (kế hoạch S2).

## Bảng endpoint

| Method | Path | File | Auth | Mục đích |
|---|---|---|---|---|
| `POST` | `/chat` | `api/routes_chat.py` | không | Hỏi, trả JSON đầy đủ |
| `POST` | `/chat/stream` | `api/routes_chat.py` | không | Hỏi, trả SSE (sau khi đã kiểm chứng xong) |
| `POST` | `/ingest` | `api/routes_admin.py` | `X-API-Key` = `ADMIN_API_KEY` | Index một thư mục dưới `DATA_ROOT` |
| `GET` | `/configs` | `api/routes_admin.py` | không | Liệt kê cấu hình trong `configs/` |
| `GET` | `/healthz` | `api/routes_admin.py` | không | `{"status": "ok", "provider": "<LLM_PROVIDER>"}` |
| `GET` | `/metrics` | `api/main.py` | không | Prometheus (chỉ khi cài extra `obs`) |
| `GET` | `/` | `api/main.py` | không | Web UI (`app/web/index.html`) |
| `GET` | `/static/*` | `api/main.py` | không | `app.js`, `styles.css` |

## `POST /chat`

### Request — `ChatRequest`

| Trường | Kiểu | Ràng buộc | Mặc định |
|---|---|---|---|
| `question` | string | 1–1000 ký tự | bắt buộc |
| `config` | string | `^[A-Za-z0-9_-]+$` (tên file trong `configs/`, không phải đường dẫn) | `"full"` |
| `as_of` | date `YYYY-MM-DD` | — | hôm nay |

```bash
curl -s -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"question": "Nghỉ việc phải báo trước bao nhiêu ngày?", "config": "full"}'
```

### Response — `ChatResponse` (= `Answer`)

| Trường | Kiểu | Nghĩa |
|---|---|---|
| `answer` | string | Văn bản cuối, kèm `[C1]…`; từ chối thì đúng `ABSTAIN_TEXT` |
| `status` | `answered` \| `partial` \| `abstained` \| `no_context` | Xem bảng dưới |
| `claims[]` | `{text, citations[], entailment, verdict, cited_as}` | **Mọi** mệnh đề, kể cả mệnh đề guard đã bỏ |
| `sources[]` | `{label, score, chunk}` | Các đoạn đưa cho LLM; `score` là điểm rerank; `chunk` có `chunk_id`, `doc_id`, `text`, `article`, `clause`, `chapter`, `doc_title`, `effective_date`, `expiry_date`, `ref`, … |
| `meta.regenerated` | bool | Đã sinh lại |
| `meta.latency_ms`, `tokens`, `llm_calls`, `cost_usd` | số | Chi phí của câu này |
| `meta.config` | string | Tên cấu hình đã dùng |
| `meta.abstain_reason` | `retrieval_floor` \| `out_of_domain` \| `model` \| `guard` \| null | Lớp nào đã dừng |
| `meta.steps[]` | `{name, ms, detail}` | Trace: `retrieve` (`query`, `top_score`), `plan` (`in_domain`, `queries`, `tokens`), `generate` (`attempt`, `tokens`, `truncated`), `verify` (`claims`, `unsupported`) |

### `status`

| Giá trị | Nghĩa |
|---|---|
| `answered` | Mọi mệnh đề còn lại đều được chứng minh (hoặc guard tắt) |
| `partial` | Guard đã bỏ một số mệnh đề, phần còn lại được trả về |
| `abstained` | Model tự từ chối, hoặc guard loại hết |
| `no_context` | Dừng trước khi LLM viết câu trả lời (floor hoặc out-of-domain) |

### `verdict`

| Giá trị | Nghĩa |
|---|---|
| `supported` | `entailment ≥ τ` |
| `unsupported` | `entailment < τ` |
| `uncited` | Không có mã trích dẫn, luôn coi là không có căn cứ |
| `null` | Guard tắt: báo cáo nhưng không kiểm chứng |

`cited_as` khác `null` khi guard đã chuyển trích dẫn sang đoạn thật sự chứng minh
mệnh đề; giá trị là nhãn model viết ban đầu.

### Mã HTTP

| Mã | Khi nào |
|---|---|
| 200 | Mọi kết quả, **kể cả từ chối** — từ chối là kết quả hợp lệ, không phải lỗi |
| 404 | `config` không tồn tại |
| 422 | Vi phạm schema (`question` rỗng/quá dài, `config` sai mẫu, `as_of` sai định dạng) |
| 503 | Provider LLM không phản hồi sau khi thử lại (`{"detail": "LLM provider unavailable: ..."}`) |

## `POST /chat/stream`

Cùng request. Server chạy **trọn** `answer_question` (kể cả kiểm chứng), rồi phát:

```
event: claim
data: {"text": "...", "citations": ["C1"], "entailment": 0.99, "verdict": "supported", "cited_as": null}

event: done
data: {"status": "answered", "answer": "...", "meta": {...}}
```

Lỗi provider → `event: error` / `data: {"detail": "..."}` (header đã gửi nên
không trả 503 được). Vì sao chờ kiểm chứng xong: người dùng không đủ chuyên môn
mà đã đọc câu sai thì gạch đi cũng không xóa được ấn tượng
([ADR-0003](../adr/0003-verify-before-stream.md)). Web UI hiện **chưa dùng**
endpoint này.

## `POST /ingest`

```http
POST /ingest
X-API-Key: dev
Content-Type: application/json

{"source": "data/sample_corpus", "config": "full"}
→ 200 {"files": 1, "chunks": 4, "written": 4}
```

| Điều kiện | Mã |
|---|---|
| Server chưa đặt `ADMIN_API_KEY` (endpoint tắt) | 403 |
| Thiếu hoặc sai `X-API-Key` (so sánh constant-time) | 401 + `WWW-Authenticate: ApiKey` |
| `source` không phải thư mục dưới `DATA_ROOT` (cả hai phía `resolve()` nên `..` và symlink không thoát được) | 400 |
| Trường lạ trong body (kể cả `recreate`) | 422 |

- `config` quyết định chunker, nên quyết định ghi vào collection nào.
- Chỉ **thêm**, không bao giờ xóa index. Xóa (`--recreate`) chỉ có ở CLI.
- Chạy **đồng bộ** trong request (embed qua pool model), có thể mất vài phút với
  corpus thật. Kế hoạch chuyển thành job nền: S4.

## `GET /configs`

```json
[{"name": "agentic", "guard_enabled": true, "entailment_threshold": 0.5,
  "corrective_enabled": true, "min_score": 0.3, "chunker": "structural"}, ...]
```

Sắp theo tên file. UI dùng `entailment_threshold` để vẽ vạch τ, nên đổi τ trong
YAML là UI đổi theo.

## Giao diện web — `app/web/`

Một trang, JS thuần, **không build step**, do chính API phục vụ (một tiến trình,
một origin, không CORS).

| File | Dòng | Nội dung |
|---|---|---|
| `index.html` | 89 | Thanh trên (chọn config, ngày `as_of`, trạng thái provider), ô hỏi, 5 câu mẫu, thước entailment có vạch τ, footer bốn lớp phòng vệ |
| `app.js` | 427 | Toàn bộ logic |
| `styles.css` | 777 | Giao diện; gradient của thước entailment là màu duy nhất có nghĩa |

### Luồng trong `app.js`

```
boot()
  GET /healthz  → hiện "provider <tên>" (hoặc "API không phản hồi")
  GET /configs  → điền <select>, lưu τ và guard_enabled của từng config
  đọc ?q=&config=&as_of= trên URL → tự hỏi nếu có q (link demo chia sẻ được)
  paintScale()  → vẽ vạch τ của config đang chọn lên thước

submit
  POST /chat {question, config, as_of?}
  lỗi HTTP      → renderFailure(status, detail)
  thành công    → render(res, config)

render
  verdictLine   trạng thái + chi phí (thời gian, số lời gọi LLM, token)
  answer        [C1] thành nút; bấm thì sáng đoạn nguồn tương ứng
  ledger        mỗi mệnh đề: chữ, verdict, nhãn trích dẫn, "model trích Cx" nếu đã sửa,
                thanh entailment có vạch τ, điểm; mệnh đề bị bỏ vẫn hiện (gạch ngang)
  layers        nếu từ chối: bốn lớp phòng vệ, đánh dấu lớp đã chặn
  tray          các đoạn nguồn (sourceCard), lọc theo mệnh đề đang chọn
  pipeline      dòng thời gian theo meta.steps, đánh số bước lặp ("Truy xuất (lần 2)")
```

`esc()` thoát HTML ở mọi chỗ chèn dữ liệu. Số thập phân hiển thị dấu phẩy kiểu
Việt Nam.

## Ví dụ nhanh bằng mock

```bash
LLM_PROVIDER=mock ADMIN_API_KEY=dev make run          # cửa sổ 1
ADMIN_API_KEY=dev make seed                           # cửa sổ 2: index data/sample_corpus
curl -s localhost:8000/healthz
curl -s localhost:8000/configs | python -m json.tool
curl -s -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"question":"Nghỉ việc phải báo trước bao nhiêu ngày?","config":"agentic"}' | python -m json.tool
# hoặc mở http://localhost:8000/?q=Nghỉ%20việc%20phải%20báo%20trước%20bao%20nhiêu%20ngày%3F
```

`make seed` từ chối chạy nếu server không ở provider `mock` (kiểm tra qua
`/healthz`) hoặc shell không có `ADMIN_API_KEY`.

---

[← 08 — Đánh giá](08-evaluation.md) · [Handbook](README.md) · [10 — Cấu hình & vận hành →](10-configuration-and-operations.md)
