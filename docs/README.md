# Tài liệu dự án grounded-rag

Tài liệu viết bằng tiếng Việt (tài liệu làm việc). `README.md` ở thư mục gốc
viết bằng tiếng Anh vì đó là mặt tiền của repo.

Quy trình: mỗi phần việc có spec trước khi có code. Yêu cầu (02) và kiến trúc
(03–06) chốt phạm vi; kế hoạch đánh giá (07) chốt cách đo **trước** khi chạy;
mọi quyết định có phương án thay thế thành một ADR; kế hoạch (08, 12, 13) chia
việc thành task có tiêu chí "xong khi" kiểm chứng được.

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
| 11 | [Spec nâng cấp v2](11-spec-v2.md) | Kho ý tưởng v2: verifier, đánh giá thống kê, serving, luật theo thời điểm. Lộ trình 12 tuần của nó đã được thay bằng 12 |
| 12 | [Đánh giá hiện trạng & kế hoạch v1.1](12-assessment-and-plan.md) | Hệ thống đang ở đâu, lỗ hổng nào chặn việc dùng thật, cắt gì, thêm gì |
| 13 | [Kế hoạch theo sprint](13-sprint-plan.md) | Task, ước lượng và tiêu chí xong của từng sprint tới `v1.1.0` (2026-11-29) |

## Handbook — bắt đầu từ đây nếu mới đọc dự án

[`handbook/`](handbook/README.md) tổng hợp toàn bộ dự án ở trạng thái hiện tại,
viết lại từ code: tổng quan, tech stack, kiến trúc, đọc code từ đâu, pipeline
từng bước, retrieval, guard, đánh giá, API, vận hành, kiểm thử, thuật ngữ, giới
hạn đã biết và cách mở rộng. Khi handbook và các tài liệu bên trên nói khác nhau,
tin handbook ([13 — lệch tài liệu](handbook/13-known-gaps.md)).

## Quyết định kiến trúc (ADR)

Mỗi quyết định đáng tranh luận được ghi lại một lần, kèm cả phương án bị loại
và điều kiện để đảo quyết định.

- [0001 — Dùng NLI thay vì LLM-as-judge](adr/0001-nli-over-llm-judge.md)
- [0002 — Qdrant làm vector store](adr/0002-qdrant-as-vector-store.md)
- [0003 — Kiểm chứng xong mới stream](adr/0003-verify-before-stream.md)
- [0004 — Chunk theo cấu trúc Điều/Khoản](adr/0004-structural-chunking.md)
- [0005 — Vòng truy xuất sửa lỗi tự viết, không dùng LangGraph](adr/0005-corrective-retrieval-loop.md)
- [0006 — BM25 cho nửa sparse của hybrid search](adr/0006-bm25-sparse-retrieval.md)
- [0007 — Không fine-tune model sinh; model mở qua giao thức OpenAI](adr/0007-no-generator-fine-tuning.md)
