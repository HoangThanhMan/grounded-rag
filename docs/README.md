# Tài liệu dự án grounded-rag

Tài liệu viết bằng tiếng Việt (tài liệu làm việc). `README.md` ở thư mục gốc
viết bằng tiếng Anh vì đó là mặt tiền của repo với người tuyển dụng.

## Đọc theo thứ tự

| # | Tài liệu | Trả lời câu hỏi |
|---|---|---|
| 01 | [Tổng quan dự án](01-project-overview.md) | Làm gì, vì sao, đo thành công bằng gì |
| 02 | [Yêu cầu](02-requirements.md) | Làm những gì và **cố tình không làm** những gì |
| 03 | [Kiến trúc](03-architecture.md) | Hệ thống gồm gì, dữ liệu chảy ra sao |
| 04 | [Thiết kế dữ liệu](04-data-design.md) | Chunk, metadata, schema lưu trữ |
| 05 | [Thiết kế API](05-api-design.md) | Endpoint, request/response, mã trạng thái |
| 06 | [Thiết kế guard](06-guard-design.md) | Phần lõi: kiểm chứng mệnh đề |
| 07 | [Kế hoạch đánh giá](07-evaluation-plan.md) | Đo cái gì, đo thế nào, ngưỡng bao nhiêu |
| 08 | [Lộ trình 3 tuần](08-roadmap.md) | Làm gì vào ngày nào |
| 09 | [Runbook](09-runbook.md) | Cài đặt, chạy, xử lý sự cố |
| 10 | [Đối chiếu tài liệu tham khảo](10-doi-chieu-tham-khao.md) | Lấy gì từ `tham_khao.md`, bỏ gì, vì sao |

## Quyết định kiến trúc (ADR)

Mỗi quyết định đáng tranh luận được ghi lại một lần, kèm cả phương án bị loại.
Đây cũng là kho câu trả lời phỏng vấn.

- [0001 — Dùng NLI thay vì LLM-as-judge](adr/0001-nli-over-llm-judge.md)
- [0002 — Qdrant làm vector store](adr/0002-qdrant-as-vector-store.md)
- [0003 — Kiểm chứng xong mới stream](adr/0003-verify-before-stream.md)
- [0004 — Chunk theo cấu trúc Điều/Khoản](adr/0004-structural-chunking.md)
- [0005 — Vòng truy xuất sửa lỗi tự viết, không dùng LangGraph](adr/0005-corrective-retrieval-loop.md)
- [0006 — BM25 cho nửa sparse của hybrid search](adr/0006-bm25-sparse-retrieval.md)
- [0007 — Không fine-tune model sinh; model mở qua giao thức OpenAI](adr/0007-no-generator-fine-tuning.md)
