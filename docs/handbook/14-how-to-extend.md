# 14 — Cách mở rộng

Công thức cho những việc hay gặp. Mỗi công thức ghi file cần sửa, test cần thêm
và cách kiểm chứng.

## Thêm một cấu hình chạy

1. Copy `configs/full.yaml` thành `configs/<tên>.yaml`, đổi `name` và tham số.
2. Không cần sửa code: `/configs`, UI, `eval.run --config configs/<tên>.yaml` tự
   nhận. Thêm vào `CONFIGS` trong `Makefile` nếu muốn có trong `make eval-all`.
3. Nếu đổi `retrieval.chunker` sang chunker chưa từng index: chạy ingest cho
   config đó.

Ví dụ ablation chỉ dense: `hybrid: false`.

## Đổi generator / thêm provider

**Provider OpenAI-compatible có sẵn** (vLLM, Ollama, Gemini, OpenAI, mọi server
nói `/chat/completions`): chỉ đổi biến môi trường `LLM_PROVIDER`, `LLM_MODEL`,
`*_BASE_URL`, `*_API_KEY`.

**Provider mới hoàn toàn:**

1. `generation/llm_client.py`: viết lớp có `async complete(system, user, *,
   temperature, max_tokens) -> LLMResponse` (và `stream`); dùng `_ConnectionPool`
   và `_post_json` để có sẵn retry/backoff; trả `truncated=True` khi provider dừng
   ở max tokens.
2. Thêm tên vào `Literal[...]` của `Settings.llm_provider` (`config.py`) và nhánh
   trong `get_llm_client`.
3. Thêm key/URL vào `Settings` và `.env.example`.
4. Test với `httpx.MockTransport` trong `tests/test_llm_client.py` (mẫu: các test
   OpenAI-compatible và Anthropic).
5. **Kiểm tra định dạng trích dẫn trước khi tin số**: model 3B từng trả `[1]` thay
   vì `[C1]`, và từng thay con số bằng mã trích dẫn ([../09-runbook.md](../09-runbook.md)).
   Chạy vài câu, xem `claims`, rồi mới `make eval-all`.

## Thêm một văn bản luật

1. Đặt file `data/corpus/<doc_id>.md` với front matter (`title`, `number`,
   `issued_by`, `effective_date`, `expiry_date` nếu đã hết hiệu lực). Văn bản cần
   "Điều <số>." / "<số>. " / "Chương <La Mã>" ở đầu dòng để chunker structural
   nhận ra.
2. Hoặc thêm nguồn vào `scripts/prepare_corpus.py` để tải từ Công báo (có kiểm tra
   đủ Điều, khoản liên tục).
3. `make ingest`. Kiểm tra số chunk và đọc vài chunk bằng mắt.
4. Cập nhật `_PROTECTED` trong `guard/claim_splitter.py` nếu văn bản có ký hiệu
   kết thúc bằng dấu chấm mới.
5. Thêm câu hỏi vào dataset theo LABELING.md, chạy `make check-dataset`.
6. Văn bản thay thế văn bản cũ: đặt `expiry_date` cho văn bản cũ để minh họa `as_of`.

## Đổi chunker

1. Sửa `ingest/chunkers.py`; thêm test vào `tests/test_chunkers.py`.
2. **Bắt buộc dựng lại index**: `python -m grounded_rag.ingest.pipeline --source
   data/corpus --config configs/full.yaml --recreate` — vì upsert chỉ thêm, chunk
   cũ sẽ nằm lẫn chunk mới.
3. `make check-dataset` (gold ref vẫn giải được?), rồi `make eval-all`.

## Đổi prompt

1. Sửa `generation/prompts.py`. Comment trong file giải thích từng quy tắc tồn tại
   vì lỗi nào — đừng xóa quy tắc mà không đọc lý do.
2. Prompt và guard đi cùng nhau: chạy lại **cả bốn** cấu hình (`make eval-all`),
   cập nhật bảng README.
3. Kiểm tra `truncated_generations == 0` trong report.

## Đổi guard (verifier, policy, τ)

1. Test trước: `tests/test_policy.py`, `test_nli_verifier.py`, `test_claim_splitter.py`.
2. `make nli-probe` — tổng số cặp sai không được tăng.
3. Đổi verifier: `python scripts/calibrate_tau.py rescore` rồi `sweep`; chọn τ,
   cập nhật `guard.entailment_threshold` trong YAML **và** `ENTAILMENT_THRESHOLD`
   nếu muốn thước đo đi theo.
4. Đổi thước đo eval mà không đổi pipeline: `python -m eval.rejudge
   reports/2026-10-12-gemini/*.json` (không gọi LLM).
5. Đổi hành vi guard: `make eval-all`.

## Thêm một metric

1. `eval/metrics.py`: thêm hàm thuần (nhận `Row` / `Answer`), thêm khóa trong
   `aggregate()`.
2. Test trong `tests/test_metrics.py` với dữ liệu biết trước kết quả.
3. Thêm cột vào `COLUMNS` của `eval/report.py` nếu muốn có trong bảng.
4. `python -m eval.rejudge reports/2026-10-12-gemini/*.json` tính lại trên report
   cũ, không cần gọi LLM.

## Thêm câu hỏi vào dataset

1. Theo đúng `eval/dataset/LABELING.md`: câu không có đáp án **viết tay** và tìm
   toàn văn trước; `gold_chunks` theo `ref`.
2. `make check-dataset` phải xanh.
3. Sau khi đã xem kết quả thì **không sửa nhãn**; buộc phải sửa thì ghi CHANGELOG
   trong LABELING.md và chạy lại bốn cấu hình.

## Thêm một endpoint

1. Thêm vào `api/routes_chat.py` hoặc `routes_admin.py` (hoặc router mới, include
   trong `api/main.py`); schema trong `api/schemas.py`.
2. Không đặt logic nghiệp vụ trong route; gọi `service` hoặc module tương ứng.
3. Lời gọi model CPU phải qua `compute.run_model`, nếu không sẽ khóa event loop
   (`tests/test_concurrency.py` là mẫu để kiểm).
4. Test bằng `TestClient` trong `tests/test_api.py`.
5. Cập nhật [09](09-api-and-ui.md) và [../05-api-design.md](../05-api-design.md).

## Thêm một bước vào pipeline

1. Thêm vào `service._answer` (hoặc `corrective.retrieve` nếu là truy xuất).
2. Bọc bằng `with trace("<tên>") as span:` để có trong `meta.steps`, Prometheus,
   Langfuse; thêm nhãn tiếng Việt vào `STEP_NAME` trong `app/web/app.js`.
3. Nếu bước có thể từ chối: thêm giá trị vào `AbstainReason` (`types.py`), cập
   nhật `LAYERS` trong `app/web/app.js` và `scripts/why_abstained.py`, và
   `eval/report.py::LAYERS`.
4. Nếu bước gọi LLM: kiểm tra `llm.left` trước khi gọi; cân nhắc tăng
   `max_llm_calls`.
5. Thêm một dòng ablation vào bảng eval.

## Chạy pipeline thật trên máy mới

```bash
python -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
make dev-install
cp .env.example .env            # LLM_PROVIDER=gemini, LLM_MODEL=gemini-3.1-flash-lite, GEMINI_API_KEY=...
make up-qdrant
make ingest                     # ~5 phút trên CPU
make run                        # http://localhost:8000
```

---

[← 13 — Giới hạn & lệch tài liệu](13-known-gaps.md) · [Handbook](README.md)
