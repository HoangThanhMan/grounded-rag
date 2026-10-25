# 13 — Giới hạn đã biết & chỗ tài liệu lệch với code

Kiểm tra trên `master` ngày 2026-10-17. Kế hoạch xử lý:
[../12-assessment-and-plan.md](../12-assessment-and-plan.md),
[../13-sprint-plan.md](../13-sprint-plan.md).

## 1. Giới hạn của kết quả

| # | Giới hạn | Hệ quả |
|---|---|---|
| R1 | NLI không tách được mệnh đề đúng/sai trên dev (6/6 mệnh đề sai ≥ 0.70) | Guard NLI chưa chứng minh được giá trị; lớp bảo vệ thật là floor, luật con số, kiểm tra trích dẫn |
| R2 | Thước đo hallucination là chính model của guard | Số 0 của `full`/`agentic` không độc lập; ≥ 3/7 câu baseline bị chấm "bịa" thực ra đúng |
| R3 | Chưa chấm tay, chưa chạy RAGAS với giám khảo thật | Chưa có đối chứng độc lập |
| R4 | n = 80, không có khoảng tin cậy | Khác biệt 1–3 câu không kết luận được |
| R5 | Không đo độ đúng (`gold_answer` không được dùng trong metric chính) | Guard đo "có căn cứ", không đo "đúng" |
| R6 | Câu hỏi sinh từ chính chunk | Retrieval recall có thể lạc quan |
| R7 | Đổi chủ thể, bỏ điều kiện, lấy số của mục bên cạnh lọt qua guard | Đúng loại lỗi của câu `near_miss` |
| R8 | p95 69 s trên CPU (yêu cầu tự đặt N1 < 6 s) | Không dùng thật được với phần cứng hiện tại |

## 2. Giới hạn của hệ thống

| # | Giới hạn | Vị trí |
|---|---|---|
| S1 | Ingest chỉ thêm; khoản đã sửa vẫn nằm trong index (lỗi **B6**) | `retrieval/store.py::upsert`; tạm thời dùng `--recreate` |
| S2 | Hiệu lực chỉ ở cấp văn bản, không ở cấp khoản (lỗi **B7**) | `types.Chunk.in_force`, ngày lấy từ `DocMeta` |
| S3 | Không có database: câu trả lời không được lưu, không có lịch sử, không có phản hồi người dùng | — |
| S4 | `/chat` không xác thực, không rate limit, không cache | `api/routes_chat.py` |
| S5 | `POST /ingest` chạy đồng bộ trong request, có thể mất vài phút | `api/routes_admin.py` |
| S6 | Model nằm chung tiến trình với API, `MODEL_WORKERS=1` → model call xếp hàng | `compute.py` |
| S7 | `LLM_PROVIDER=mock` bật mock cho **mọi** thành phần → không load test được "model thật + LLM giả" | các hàm `get_*` |
| S8 | `CONFIG_DIR = Path("configs")` tương đối → server phải chạy từ gốc repo | `api/routes_chat.py` |
| S9 | Chỉ hỏi một lượt, không có ngữ cảnh hội thoại | — |
| S10 | Corpus chỉ 2 luật, chưa hợp nhất sửa đổi, chưa có nghị định/thông tư; `ref` trong Điều 219 BLLĐ không đáng tin | `data/corpus/` |
| S11 | Web UI gọi `/chat`, không dùng SSE; không có sự kiện tiến độ trong ~24 s chờ | `app/web/app.js` |
| S12 | Log dạng text, không có request-id; không có Prometheus server/Grafana trong compose | `api/main.py`, `docker-compose.yml` |
| S13 | Không có demo public, không có CD | — |

## 3. Điểm lệch nhỏ trong code

| # | Vấn đề | Vị trí | Gợi ý |
|---|---|---|---|
| C1 | `GenerationConfig.require_citations` được khai báo và ghi trong mọi YAML nhưng **không có code nào đọc** | `config.py`, `configs/*.yaml` | Xóa trường, hoặc dùng nó để chọn prompt |
| C2 | `__version__ = "0.1.0"` trong khi `pyproject.toml` và FastAPI ghi `0.2.0` | `src/grounded_rag/__init__.py` | Lấy version từ một nguồn |
| C3 | `.venv` local có **langfuse 4.15**, trong khi `pyproject.toml` khai báo `langfuse>=2.53,<3` và code dùng API v2 (`client.trace(...)`) | `observability/tracing.py` | `pip install "langfuse>=2.53,<3"` trong `.venv`; export hiện sẽ chỉ ghi warning |
| C4 | `ENTAILMENT_THRESHOLD` (thước đo) và `guard.entailment_threshold` (guard) là hai nơi | `config.py`, YAML | Cố ý tách; `eval.run` cảnh báo khi lệch |
| C5 | `data/corpus` (`*.md`) được commit nhưng `.cache/corpus_raw` thì không | `.gitignore` | Đúng thiết kế |

## 4. Tài liệu cũ không còn khớp code

Khi đọc `docs/01`–`docs/11` và ADR, lưu ý các chỗ sau:

| Tài liệu | Nói | Thực tế |
|---|---|---|
| [../03-architecture.md](../03-architecture.md), mục Quan sát | Langfuse: "đẩy trace lên vẫn là TODO tuần 3" | Đã cài đặt trong `observability/tracing.py::export` (test bằng client giả, chưa xem trên UI thật) |
| [../03-architecture.md](../03-architecture.md), bảng công nghệ | Demo: Streamlit | Web UI `app/web/` phục vụ ở `/`; Streamlit là demo cũ |
| [../04-data-design.md](../04-data-design.md), mục Corpus | "`data/corpus/` không commit (xem `.gitignore`)" | **Được commit**; `.gitignore` ghi rõ lý do |
| [../04-data-design.md](../04-data-design.md), mục Metadata | "Bộ luật Lao động 2012 và 2019 cùng nằm trong corpus" | Corpus chỉ có BLLĐ 2019 và Luật BHXH 2024 |
| [../05-api-design.md](../05-api-design.md), `GET /configs` | Ví dụ `entailment_threshold: 0.6` | YAML dùng 0.50 |
| [../adr/0003-verify-before-stream.md](../adr/0003-verify-before-stream.md) | "Có cờ `stream_unverified=true` để so sánh trải nghiệm" | Không có cờ này trong code |
| [../09-runbook.md](../09-runbook.md), Cài đặt | `cd ~/Data/project/grounded-rag` | Đường dẫn repo khác trên máy hiện tại; dùng gốc repo của bạn |
| [../09-runbook.md](../09-runbook.md), Chạy thật | `make demo  # streamlit :8501` là bước chính | UI chính ở `http://localhost:8000` |
| [../02-requirements.md](../02-requirements.md), Ngoài phạm vi | "Frontend hoàn chỉnh — Streamlit là đủ" | Đã có web UI riêng |
| [../08-roadmap.md](../08-roadmap.md), Tuần 3 ngày 19 | "Streamlit tô màu verdict" | Đã làm trên web UI |
| `README.md`, Stack | Liệt kê RAGAS và Langfuse | RAGAS chưa chạy với giám khảo thật; Langfuse chưa kiểm chứng trên UI |

Các tài liệu này không bị sửa trong handbook để giữ lịch sử quyết định; việc dọn
dẹp nằm trong S0 và S6-07 của [../13-sprint-plan.md](../13-sprint-plan.md).

---

[← 12 — Thuật ngữ](12-glossary.md) · [Handbook](README.md) · [14 — Cách mở rộng →](14-how-to-extend.md)
