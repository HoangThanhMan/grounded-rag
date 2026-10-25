# 12 — Đánh giá hiện trạng & kế hoạch v1.1

| | |
|---|---|
| Trạng thái | **Đề xuất** — chờ duyệt trước khi bắt đầu tuần 1 |
| Ngày | 2026-10-17 |
| Thay thế | Kế hoạch 12 tuần ở [11](11-spec-v2.md) §9. Tài liệu 11 giữ lại làm kho ý tưởng, không còn là lộ trình |
| Thời lượng | 6 sprint việc + 1 sprint đệm, ~3h/ngày, một người — lịch và task chi tiết ở [13](13-sprint-plan.md) |
| Đầu ra cuối | Tag `v1.1.0`, demo public, README có số đã được người kiểm chứng kèm khoảng tin cậy |

---

## Mục lục

1. [Tóm tắt](#1-tóm-tắt)
2. [Đã kiểm chứng những gì](#2-đã-kiểm-chứng-những-gì)
3. [Năng lực hệ thống: có gì, thiếu gì](#3-năng-lực-hệ-thống-có-gì-thiếu-gì)
4. [Tính ứng dụng](#4-tính-ứng-dụng)
5. [Nhiều người dùng được không](#5-nhiều-người-dùng-được-không)
6. [Deploy được không](#6-deploy-được-không)
7. [Phương pháp đánh giá RAG](#7-phương-pháp-đánh-giá-rag)
8. [Trạng thái các lỗi B1–B9 của spec 11](#8-trạng-thái-các-lỗi-b1b9-của-spec-11)
9. [Quyết định phạm vi: cắt, sửa, giữ, không làm](#9-quyết-định-phạm-vi-cắt-sửa-giữ-không-làm)
10. [Kế hoạch theo nhóm việc](#10-kế-hoạch-theo-nhóm-việc)
11. [Định nghĩa "xong" cho v1.1](#11-định-nghĩa-xong-cho-v11)
12. [Rủi ro](#12-rủi-ro)
13. [ADR cần viết](#13-adr-cần-viết)
14. [Câu hỏi thiết kế phải có câu trả lời](#14-câu-hỏi-thiết-kế-phải-có-câu-trả-lời)

---

## 1. Tóm tắt

Phần **chất lượng câu trả lời** của v1 đã đo được: benchmark tự xây với 40% câu
không có đáp án, 4 cấu hình chấm bằng cùng một thước đo, ADR cho mọi quyết định
có phương án thay thế, và mục Limitations viết từ số đo.

Bốn lỗ hổng chặn nó khỏi mức "đưa cho người khác dùng được":

| # | Lỗ hổng | Ảnh hưởng tới |
|---|---|---|
| L1 | Con số hallucination chưa có kiểm chứng độc lập, và thước đo NLI chấm sai cả câu đúng của baseline (§7.2) | AI: độ tin của bảng Results |
| L2 | Chưa có demo public, chưa có CD | Người dùng: muốn thử phải clone repo và tự cài model |
| L3 | Không có database, không có job bất đồng bộ, không có auth/rate limit cho `/chat` | Dịch vụ: không lưu được câu trả lời, ingest chặn request, link public tiêu hết quota |
| L4 | p95 69 s trên CPU so với yêu cầu N1 < 6 s, chưa có load test | Dịch vụ: không biết hệ thống chịu tải tới đâu |

Kế hoạch v1.1 chỉ nhắm vào bốn lỗ hổng này. Phần lõi (retrieval, guard, eval)
giữ nguyên. Lớp mới thêm vào là **backend**, không phải frontend: UI vẫn là
`app/web/` JS thuần, chỉ thêm sự kiện tiến độ và nút phản hồi.

---

## 2. Đã kiểm chứng những gì

Chạy ngày 2026-10-17 trên `master` (`2e85cdc`):

| Kiểm tra | Kết quả |
|---|---|
| `make test` | 135 passed, 7,4 s |
| `make lint` | sạch |
| `scripts/check_dataset.py` | 100 câu, 1.230 khoản; 1 cảnh báo `u018` (đã ghi trong [LABELING.md](../eval/dataset/LABELING.md)) |
| CI GitHub Actions | lần chạy gần nhất xanh (2026-10-12); repo public |
| `python -m eval.report reports/2026-10-12-gemini/*.json` | khớp từng số với bảng Results trong README; 0 câu `errored`, 0 `truncated_generations` |
| Đọc tay 7 câu baseline bị thước đo chấm "bịa" | ≥ 3 câu đúng nguyên văn luật — xem §7.2 |

Quy mô: ~3.850 dòng trong `src/` + `eval/`, 18 file test, ~3.100 dòng tài liệu.

---

## 3. Năng lực hệ thống: có gì, thiếu gì

### 3.1 Chất lượng câu trả lời

| Năng lực | Hiện trạng | Kế hoạch |
|---|---|---|
| Truy xuất | Chunk theo Điều/Khoản ([ADR-0004](adr/0004-structural-chunking.md)), bge-m3 + BM25 ([ADR-0006](adr/0006-bm25-sparse-retrieval.md)), cross-encoder rerank, retrieval floor | Giữ; thêm recall@k, MRR (tuần 1) |
| Sinh câu trả lời | Nhiều provider qua config; prompt sửa theo lỗi đo được ([09](09-runbook.md)) | Giữ |
| Kiểm soát bịa | NLI guard, luật con số, kiểm tra citation ([06](06-guard-design.md)) | Giữ; đo lại bằng nhãn người (tuần 1) |
| Đánh giá | Benchmark 100 câu, dev/test, một thước đo, ablation closed-book | Thêm khoảng tin cậy, so sánh cặp, `answer_correctness`, chấm tay (tuần 1) |
| Điều phối nhiều bước | Một vòng corrective tự viết, có ngân sách ([ADR-0005](adr/0005-corrective-retrieval-loop.md)) | Giữ |
| Tinh chỉnh model | Không — cố ý ([ADR-0007](adr/0007-no-generator-fine-tuning.md)) | Ngoài phạm vi |

### 3.2 Năng lực dịch vụ

| Năng lực | Hiện trạng | Kế hoạch |
|---|---|---|
| REST API, validation | FastAPI, Pydantic, mã trạng thái có chủ đích (từ chối = 200, provider chết = 503) | `/v1`, problem+json (tuần 2) |
| Streaming | SSE, kiểm chứng xong mới stream ([ADR-0003](adr/0003-verify-before-stream.md)) | Thêm sự kiện tiến độ (tuần 3) |
| Concurrency | Pool chạy model ngoài event loop, ưu tiên request đến trước (`src/grounded_rag/compute.py`), có test | Giữ |
| Bảo mật | Admin key so sánh constant-time, chặn path traversal ở `/ingest` | API key có hash + scope (tuần 2) |
| Lưu trữ | **Không có** database | Postgres + Alembic (tuần 2) |
| Job nền | **Không có** — ingest chạy đồng bộ trong request | Hàng đợi trên Postgres (tuần 3) |
| Giới hạn truy cập, cache | **Không có** cho `/chat` | Rate limit, cache câu trả lời (tuần 2) |
| Đóng gói, CI | Image non-root, healthcheck, Actions trên Python 3.12 và 3.14 | Thêm CD (tuần 4) |
| Quan sát | `/metrics` Prometheus, `meta.steps`, trace Langfuse | Log JSON + request-id (tuần 2) |
| Hiệu năng | **Chưa đo** dưới tải | Load test (tuần 4) |
| Triển khai | **Không có** | Demo public (tuần 4) |

---

## 4. Tính ứng dụng

**Bài toán chọn đúng.** Tra cứu luật lao động và BHXH có người dùng thật (người
lao động, HR), và đây là lĩnh vực mà từ chối tốt hơn bịa ([02](02-requirements.md)).
Đọc luật theo ngày `as_of` cho thấy có hiểu nghiệp vụ.

Giới hạn khi dùng thật — ghi vào README, không cần sửa hết trong v1.1:

- Corpus chỉ 2 luật, chưa có nghị định, thông tư hướng dẫn.
- Mỗi câu hỏi độc lập, không hỏi tiếp theo ngữ cảnh.
- Hiệu lực áp ở cấp văn bản, chưa ở cấp khoản (B7, §8).
- p50 ~24 s trên CPU: chậm với người dùng thật. v1.1 không hứa sửa; v1.1 làm
  cho việc chờ đó **nhìn thấy được** (sự kiện tiến độ) và **đo được** (load test).

---

## 5. Nhiều người dùng được không

Hiện tại: demo cho vài người, chưa phải dịch vụ.

| Điểm nghẽn | Vị trí | Hệ quả |
|---|---|---|
| `MODEL_WORKERS=1`: embed, rerank, NLI xếp hàng qua một luồng | `compute.py`, `.env.example` | Vài request đồng thời là chờ hàng chục giây |
| `/chat` không auth, không rate limit | `api/routes_chat.py` | Link public tiêu hết quota LLM free tier |
| Không cache câu trả lời | — | Câu hỏi lặp lại vẫn tốn trọn pipeline |
| Model nằm chung tiến trình với API | `compute.py` (tự ghi là giải pháp tạm) | Không scale API và model riêng được |
| Không có DB | — | Không có lịch sử, không có phản hồi, không đếm được ai dùng gì |

Mục tiêu của v1.1 không phải chịu tải lớn mà là **biết điểm bão hòa ở đâu và
vì sao** — một load test có số trước/sau (tuần 4). Tách model ra tiến
trình riêng (WS5a của [11](11-spec-v2.md)) là việc tùy chọn, chỉ làm nếu còn thời gian.

---

## 6. Deploy được không

**Về kỹ thuật được, nhưng chưa ai deploy** (repo không có homepage URL).

Đã sẵn sàng: Dockerfile cài torch bản CPU, chạy non-root, có `HEALTHCHECK`;
compose pin phiên bản Qdrant, Ollama, vLLM; cấu hình hoàn toàn qua biến môi trường.

Phải tính trước khi deploy:

| Vấn đề | Cách xử lý trong v1.1 |
|---|---|
| RAM: bge-m3 + reranker + mDeBERTa ước ~5–6 GB | Chọn nền tảng có ≥ 8 GB RAM. Ứng viên: Hugging Face Spaces (Docker, CPU) — **kiểm tra lại giới hạn gói free trước khi chọn** |
| Qdrant | Qdrant Cloud gói free (1.2k chunk là rất nhỏ) |
| Postgres (mới ở tuần 2) | Postgres managed gói free, ví dụ Neon hoặc Supabase |
| Quota LLM | Rate limit theo client + cache câu trả lời (tuần 2) |
| Secret dev của Langfuse trong compose | Không deploy Langfuse; chỉ dùng ở local |
| Model tải lại mỗi lần khởi động | Cache HF trên volume, hoặc chấp nhận khởi động chậm và ghi vào runbook |

---

## 7. Phương pháp đánh giá RAG

### 7.1 Điểm mạnh — giữ nguyên

- 40% câu không có đáp án, chia ba loại bẫy (`out_of_scope`, `false_premise`, `near_miss`).
- Tách dev/test; τ chỉ hiệu chỉnh trên 20 câu dev.
- Một thước đo cho mọi cấu hình, chấm sau khi chạy ([07](07-evaluation-plan.md)).
- Gold so khớp theo nội dung, nên so sánh hai chunker công bằng.
- Bảng "lớp nào chặn câu không trả lời được", ablation closed-book.
- `check-dataset` chạy trong CI; `eval.rejudge` chấm lại không cần gọi LLM.

### 7.2 Vấn đề — đã kiểm chứng

**E1. Cột Halluc. đang đo nhiễu của NLI nhiều hơn đo việc bịa.** Bảy câu
baseline bị chấm "bịa" trong `reports/2026-10-12-gemini/baseline.json`, đọc đối
chiếu với văn bản luật:

| Câu | Mệnh đề bị chấm | Điểm | Đối chiếu |
|---|---|---|---|
| `a014` | "Mỗi năm làm việc … trợ cấp thôi việc một nửa tháng tiền lương" | 0.44 | **Đúng** — `data/corpus/bo_luat_lao_dong_2019.md:290` |
| `a057` | "Mức trợ cấp mai táng bằng 10 lần mức tham chiếu …" | 0.19 | **Đúng** — `data/corpus/luat_bao_hiem_xa_hoi_2024.md:726` |
| `a052` | Nghỉ dưỡng sức "tối đa là 10 ngày" | 0.23 | **Đúng** về con số — `luat_bao_hiem_xa_hoi_2024.md:437` |
| `a044` | Hai mệnh đề gần như chép lại gold answer | 0.20 | Gần như chắc đúng — cần chấm tay |
| `a012`, `a023`, `a047` | Thêm ngoại lệ / mở rộng phạm vi | 0.06–0.41 | Chưa kết luận — cần chấm tay |

Hệ quả: chênh lệch "baseline 0.088 → full 0.000" **chưa chứng minh guard có
ích**. README đã cảnh báo đo vòng tròn; thực tế còn tệ hơn: thước đo sai ngay
trên baseline.

**E2. Không đo độ đúng.** `gold_answer` có trong dataset nhưng không metric chính
nào dùng tới. Guard kiểm *có căn cứ*, không kiểm *đúng* — [07](07-evaluation-plan.md)
tự ghi đây là hai chuyện khác nhau.

**E3. Chưa có đối chứng độc lập.** Chấm tay 30 câu và RAGAS với giám khảo thật
đều chưa làm ([08](08-roadmap.md), mục "Định nghĩa xong").

**E4. Mẫu nhỏ, không có khoảng tin cậy.** n = 80 cho nửa độ rộng CI 95% ≈ ±0.078
([11](11-spec-v2.md) §4.3). Mọi khác biệt trong bảng là 1–3 câu.

**E5. Thiên lệch do cách tạo dataset.** Câu `answerable` được LLM sinh từ chính
chunk (LABELING.md bước 1), nên dùng từ gần văn bản; retrieval recall 0.97 có thể
cao hơn với câu hỏi người dùng thật. Một người gán nhãn, không có độ đồng thuận.

**E6. CI gate là smoke test.** Chạy `mock` trên 6 câu và bỏ qua ngưỡng khi dùng
tập mẫu (`eval/run.py`). Nó chứng minh pipeline chạy được, không chặn hồi quy chất lượng.

**E7. Metric retrieval thô.** Chỉ có "gold có lọt vào context không"; chưa có
recall@k, MRR.

E1–E4 và E7 sửa ở tuần 1. E5 ghi vào Limitations. E6 đổi tên bước CI cho đúng.

---

## 8. Trạng thái các lỗi B1–B9 của spec 11

Kiểm lại trên code ngày 2026-10-17:

| # | Lỗi | Trạng thái | Bằng chứng |
|---|---|---|---|
| B1 | Model CPU chặn event loop | **Đã sửa** | `compute.py`, `tests/test_concurrency.py` |
| B2 | `/ingest` không auth, đường dẫn tùy ý | **Đã sửa** | `require_admin`, `corpus_dir` trong `api/routes_admin.py` |
| B3 | Anthropic luôn gửi `temperature` | **Đã sửa** | `ANTHROPIC_SEND_TEMPERATURE` |
| B4 | Cache NLI không giới hạn | **Đã sửa** | LRU có `NLI_CACHE_SIZE` trong `guard/nli_verifier.py` |
| B5 | Mỗi lời gọi LLM một `AsyncClient` | **Đã sửa** | client dùng chung, đóng ở `lifespan` |
| B6 | Ingest chỉ thêm, khoản đã sửa vẫn nằm trong index | **Còn** | `retrieval/store.py` `upsert` chỉ ghi chunk mới → **tuần 3** |
| B7 | Hiệu lực chỉ ở cấp văn bản | **Còn** | `types.py` `in_force` → ngoài phạm vi v1.1, ghi Limitations |
| B8 | Docker root, không healthcheck, không pin | **Đã sửa** | `Dockerfile`, `docker-compose.yml` |
| B9 | Không remote, không CI badge | **Đã sửa** | GitHub public, badge trong README |

---

## 9. Quyết định phạm vi: cắt, sửa, giữ, không làm

### 9.1 Cắt

| Cắt | Lý do |
|---|---|
| Lộ trình 12 tuần ở [11](11-spec-v2.md) §9 | Fine-tune verifier, conformal, dataset 300 câu, OTel/Grafana, MCP, công bố HF: công sức lớn so với phần chất lượng đổi lại được. 11 giữ làm kho ý tưởng |
| `app/streamlit_demo.py`, target `make demo`, extra `demo` | Trùng web UI ở `/` |
| Langfuse và RAGAS khỏi dòng Stack của README **nếu** chưa chạy thật | README chỉ ghi thứ đã chạy thật. Chạy một lần + ảnh chụp thì giữ |
| Gộp tài liệu 01–05 thành một file kiến trúc ngắn | 3.100 dòng là quá nhiều để giữ khớp với code. Giữ ADR, 06, 07, 09 |

### 9.2 Sửa

- **Đầu README**: 3 dòng tóm tắt, link demo, GIF. Bảng số chuyển xuống dưới.
- **Con số chủ đạo**: không dùng "hallucination 0.000" làm kết quả chính. Sau tuần 1,
  dẫn số có nhãn người và các kết quả không phụ thuộc thước đo NLI (ví dụ
  retrieval floor chặn 17/30 câu không trả lời được trước khi gọi LLM).
- **Bước CI "Benchmark gate"** đổi tên thành "Pipeline smoke test (mock)".
- `reports/*` đang bị `.gitignore`: kết quả chấm tay (`reports/hand-graded.json`)
  phải được đưa vào git như `reports/2026-10-12-gemini/`.

### 9.3 Giữ

- Cấu hình `agentic`: kết quả âm có đo đạc vẫn là kết quả, và nó đo chi phí của vòng lặp.
- Profile vLLM / Ollama: gần như không tốn gì.
- Frontend JS thuần, không build step. Phần việc của v1.1 nằm ở backend.

### 9.4 Không làm trong v1.1

React/TypeScript, đăng ký/đăng nhập người dùng, OAuth, multi-tenant,
Kubernetes, Redis (trừ khi rate limit cần nhiều replica), fine-tune, hiệu lực
cấp khoản (B7), chat nhiều lượt.

---

## 10. Kế hoạch theo nhóm việc

Bốn nhóm việc dưới đây là **nội dung**. Lịch là ở [13](13-sprint-plan.md): ước
lượng chi tiết cho thấy 4 tuần không đủ, nên các nhóm được chia lại thành sprint.

| Nhóm việc | Sprint trong [13](13-sprint-plan.md) |
|---|---|
| Tuần 1 — Đánh giá đáng tin | S1 |
| Tuần 2 — Lõi backend | S2, S3 |
| Tuần 3 — Job nền & reindex | S4 |
| Tuần 4 — Hiệu năng, deploy, đóng gói | S5, S6 |

### Tuần 1 — Đánh giá đáng tin (sửa L1)

| Việc | Xong khi |
|---|---|
| Chấm tay 30 câu: `scripts/hand_grade.py sample` trên 4 report 2026-10-12, rồi `score` | `reports/hand-graded.json` có 30 nhãn, được commit; bảng "nhãn người vs thước đo NLI" (đồng ý / NLI chấm oan / NLI bỏ lọt) |
| Chấm tay riêng 7 câu baseline ở §7.2 | Biết bao nhiêu trong 0.088 là bịa thật |
| Khoảng tin cậy bootstrap trong `eval/report.py` (theo câu, 10.000 lần, seed cố định) | Bảng README có `0.08 [0.03, 0.15]`; test với dữ liệu biết trước |
| So sánh cặp giữa cấu hình (bootstrap cặp hoặc McNemar trên cùng câu hỏi) | Một dòng: chênh lệch nào có ý nghĩa, chênh lệch nào không |
| `answer_correctness`: số trong `gold_answer` có mặt trong câu trả lời, cộng nhãn người trên mẫu | Cột mới trong report; không cần gọi LLM lại |
| `recall@k`, `MRR` cho retrieval | Có trong `eval/metrics.py` + test |
| LLM judge trên đúng 30 câu đã chấm tay (`eval/ragas_eval.py`, giám khảo khác họ generator) | Độ đồng thuận judge–người; quyết định có dùng judge cho phần còn lại không |

**Mốc:** README nói được guard có ích hay không, bằng nhãn người, kèm khoảng tin cậy.
Nếu kết quả xấu: viết ra, không chỉnh số ([07](07-evaluation-plan.md) — Kỷ luật).

### Tuần 2 — Lõi backend (sửa L3)

| Việc | Xong khi |
|---|---|
| Postgres + SQLAlchemy 2 (async) + Alembic. Bảng: `requests`, `answers`, `claims`, `feedback`, `api_keys`, `jobs` | `alembic upgrade head` trên DB trống; compose có service `postgres`; test chạy với Postgres trong CI (service container) |
| Lưu mỗi `/chat` vào DB: câu hỏi, config, `as_of`, status, claims, `meta` | `GET /v1/requests/{id}` trả lại đúng câu trả lời đã phục vụ |
| Tiền tố `/v1`, lỗi theo `application/problem+json` (RFC 9457), middleware `X-Request-ID` | Mọi lỗi 4xx/5xx cùng một dạng; request-id có trong log và response |
| Log có cấu trúc (JSON), một dòng mỗi request: id, config, status, latency, llm_calls | Truy được một request từ log tới DB |
| API key theo client: lưu **hash**, có scope (`chat`, `admin`); thay `ADMIN_API_KEY` | Test: key sai → 401, sai scope → 403, key bị thu hồi → 401 |
| Rate limit token bucket theo key/IP, trong tiến trình (một replica) | Vượt ngưỡng → 429 kèm `Retry-After`; giới hạn "một replica" ghi trong ADR |
| Cache câu trả lời: khóa = câu hỏi chuẩn hóa + config + `as_of` + phiên bản index | Câu lặp lại trả trong < 50 ms, `meta.cached: true`; đổi index thì cache tự vô hiệu |
| `POST /v1/feedback`: 👍/👎 hoặc "báo sai" cho một mệnh đề; nút tương ứng trong `app/web/` | Script xuất phản hồi thành ứng viên cho tập đánh giá |

**Mốc:** mọi câu trả lời đã phục vụ đều tra lại được, có chủ, có giới hạn.

### Tuần 3 — Job nền & reindex (sửa B6)

| Việc | Xong khi |
|---|---|
| `POST /v1/ingest/jobs` → `202` + `job_id`; `GET /v1/ingest/jobs/{id}` trả trạng thái và tiến độ | Request trả ngay, không chờ embed |
| Worker riêng (`python -m grounded_rag.worker`) lấy job bằng `SELECT … FOR UPDATE SKIP LOCKED` | Hai worker không bao giờ nhận cùng một job (có test); job đang chạy mà worker chết thì được nhận lại sau timeout |
| Retry có giới hạn, trạng thái `failed` kèm lỗi | Job lỗi không làm worker chết |
| Reindex qua collection có phiên bản + alias `live` của Qdrant, đổi alias nguyên tử | Khoản bị sửa/xóa biến mất khỏi kết quả sau reindex (B6); `/chat` không lỗi trong lúc đổi alias; rollback bằng một lệnh |
| SSE sự kiện tiến độ: `retrieving` → `generating` → `verifying` → `claim` → `done` | UI hiện bước đang chạy; vẫn giữ [ADR-0003](adr/0003-verify-before-stream.md): không mệnh đề nào ra trước khi được kiểm chứng |

**Mốc:** ingest sống qua restart, reindex không downtime.

### Tuần 4 — Hiệu năng, deploy, đóng gói (sửa L2, L4)

| Việc | Xong khi |
|---|---|
| Load test bằng k6 hoặc Locust: 1 → 10 người dùng ảo, provider mock và provider thật | Báo cáo trong [09](09-runbook.md): throughput bão hòa, p50/p95/p99, `/healthz` p99 khi đang tải, bước nào nghẽn |
| Một tối ưu có số trước/sau, ví dụ `rerank_candidates` 20 → 8 hoặc `MODEL_WORKERS` | Một dòng ablation: latency đổi bao nhiêu, retrieval recall mất bao nhiêu |
| Deploy: API + worker (Docker), Postgres managed, Qdrant Cloud | Link public trả lời được; secret chỉ nằm ở biến môi trường của nền tảng |
| CD: GitHub Actions deploy khi `master` xanh; chạy `alembic upgrade` trước khi đổi bản | Một push → bản mới chạy, không thao tác tay |
| README: tóm tắt, link demo, GIF, bảng số có CI và nhãn người, Limitations cập nhật | Người lạ hiểu dự án trong 2 phút |
| Video demo 90 giây | Link trong README |

**Mốc:** tag `v1.1.0`.

**Tùy chọn, chỉ khi còn đệm:** tách embed/rerank/NLI ra tiến trình riêng
(WS5a của [11](11-spec-v2.md)) và chạy lại load test để so.

**Quy tắc lùi việc:** trễ quá 3 ngày thì cắt theo thứ tự: video → feedback UI
(giữ endpoint) → so sánh cặp → cache. **Không bao giờ cắt** chấm tay, Postgres,
job ingest, deploy.

---

## 11. Định nghĩa "xong" cho v1.1

- [ ] 30 câu chấm tay được commit; README dẫn số nhãn người
- [ ] Bảng Results có khoảng tin cậy 95%
- [ ] `answer_correctness`, `recall@k`, `MRR` có trong report
- [ ] Postgres + Alembic; mọi `/chat` được lưu và tra lại được
- [ ] API `/v1`, problem+json, request-id, log JSON
- [ ] API key có hash + scope; rate limit trả 429; cache câu trả lời
- [ ] Ingest qua job nền (`SKIP LOCKED`), sống qua restart
- [ ] Reindex qua alias, B6 có test
- [ ] SSE có sự kiện tiến độ
- [ ] Load test có báo cáo
- [ ] Demo public + CD
- [ ] Streamlit đã xóa; Stack trong README chỉ ghi thứ đã chạy thật
- [ ] ADR 0008–0010 (§13)

---

## 12. Rủi ro

| Rủi ro | Dấu hiệu sớm | Xử lý |
|---|---|---|
| Chấm tay cho thấy guard không có ích | Tuần 1 | Báo cáo trung thực; kết luận chuyển sang "lớp rẻ (floor, luật con số, citation) mới là thứ bảo vệ". **Không chỉnh số** |
| Gói free không đủ RAM cho 3 model | Deploy thử ở đầu tuần 4 thất bại | Reranker nhỏ hơn hoặc tắt reranker ở bản demo, ghi rõ trong README; hoặc demo dùng ONNX/int8 |
| Hết quota LLM khi demo public | 429 từ provider | Rate limit chặt hơn, cache, fallback Ollama |
| Postgres trong CI làm test chậm/flaky | Tuần 2 | Unit test giữ in-memory; chỉ test tích hợp dùng service container |
| Phạm vi trượt sang v2 | Bắt đầu làm conformal, fine-tune | Đối chiếu §9.4 trước mỗi việc mới |

---

## 13. ADR cần viết

| ADR | Quyết định | Phương án bị loại |
|---|---|---|
| 0008 | Postgres làm hàng đợi job (`SKIP LOCKED`) | Celery + Redis, RQ, `BackgroundTasks` của FastAPI |
| 0009 | Rate limit trong tiến trình, một replica | Redis, rate limit ở reverse proxy |
| 0010 | Reindex bằng collection có phiên bản + alias | Xóa rồi ghi lại tại chỗ, upsert kèm xóa chunk cũ |

---

## 14. Câu hỏi thiết kế phải có câu trả lời

Mỗi câu dưới đây là một quyết định có phương án thay thế. v1.1 chỉ xong khi câu
trả lời nằm trong tài liệu được dẫn bên cạnh, không chỉ nằm trong code:

- Vì sao NLI thay vì LLM judge, và vì sao kết quả cho thấy NLI chưa đủ? ([ADR-0001](adr/0001-nli-over-llm-judge.md), [06](06-guard-design.md))
- Đo hallucination bằng chính model của guard sai ở đâu, và sửa bằng gì? (§7.2, tuần 1)
- Vì sao vòng corrective tự viết thay vì dùng LangChain / LangGraph? ([ADR-0005](adr/0005-corrective-retrieval-loop.md))
- Model đồng bộ trong handler async gây ra gì? Vì sao không dùng `asyncio.to_thread`? (`compute.py`)
- Vì sao Postgres làm hàng đợi chứ không Celery? `SKIP LOCKED` làm gì? (ADR-0008)
- Rate limit trong tiến trình hỏng khi nào? (ADR-0009)
- Đổi alias khi đang có request thì chuyện gì xảy ra? (ADR-0010)
- Load test cho thấy nghẽn ở đâu, và scale thế nào nếu có GPU / nhiều máy? ([09](09-runbook.md), tuần 4)
- Khác biệt 0.02 giữa hai cấu hình có ý nghĩa không? (khoảng tin cậy, tuần 1)

---

[← 11 — Spec v2](11-spec-v2.md) · [Mục lục tài liệu](README.md) · [13 — Kế hoạch theo sprint →](13-sprint-plan.md)
