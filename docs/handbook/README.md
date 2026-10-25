# Handbook — hiểu toàn bộ grounded-rag

Bộ tài liệu này tổng hợp **mọi thứ cần biết về dự án ở trạng thái hiện tại**
(`master`, 2026-10-17): dự án làm gì, kiến trúc, tech stack, đọc code từ đâu,
từng module hoạt động thế nào, đánh giá ra sao, vận hành thế nào.

Khác với các tài liệu `docs/01`–`docs/13` (viết dần theo tiến độ, một số chỗ đã
cũ), handbook được viết lại **từ code**. Khi handbook và tài liệu cũ nói khác
nhau, tin handbook và xem [13 — Lệch giữa tài liệu và code](13-known-gaps.md).

---

## Đọc theo mục đích

| Bạn muốn | Đọc | Thời gian |
|---|---|---|
| Hiểu dự án trong 15 phút | [01](01-overview.md) → [03](03-architecture.md) (chỉ phần sơ đồ) | 15 phút |
| Bắt đầu đọc code | [04](04-code-reading-guide.md) → [05](05-query-pipeline.md) | 1–2 giờ |
| Hiểu sâu phần AI | [06](06-ingest-and-retrieval.md) → [07](07-guard.md) → [08](08-evaluation.md) | nửa ngày |
| Chạy, sửa cấu hình, debug | [10](10-configuration-and-operations.md) → [11](11-testing.md) | 1 giờ |
| Thêm tính năng | [14](14-how-to-extend.md) | khi cần |
| Chuẩn bị phỏng vấn | [01](01-overview.md), [07](07-guard.md) mục "Guard sai ở đâu", [08](08-evaluation.md) mục "Điểm yếu", [13](13-known-gaps.md) | 2 giờ |

## Mục lục

| # | Tài liệu | Nội dung |
|---|---|---|
| 01 | [Tổng quan](01-overview.md) | Bài toán, giải pháp, người dùng, kết quả đo được, trạng thái |
| 02 | [Tech stack](02-tech-stack.md) | Từng công nghệ: vai trò, phiên bản, nằm ở file nào, vì sao chọn, cái bị loại |
| 03 | [Kiến trúc](03-architecture.md) | Thành phần, tiến trình, luồng offline/online, phụ thuộc giữa module, chế độ mock |
| 04 | [Hướng dẫn đọc code](04-code-reading-guide.md) | Bản đồ repo, thứ tự đọc, từng file làm gì, gọi ai |
| 05 | [Pipeline truy vấn](05-query-pipeline.md) | Theo một request từ HTTP tới response, từng bước, mọi nhánh rẽ |
| 06 | [Ingest & retrieval](06-ingest-and-retrieval.md) | Corpus, loader, chunker, Qdrant, BM25, RRF, rerank, floor, `as_of`, vòng corrective |
| 07 | [Guard](07-guard.md) | Tách mệnh đề, NLI, luật con số, premise views, sửa trích dẫn, policy, τ |
| 08 | [Đánh giá](08-evaluation.md) | Dataset, thước đo, metric, các script, report, kết quả, điểm yếu |
| 09 | [API & giao diện](09-api-and-ui.md) | Endpoint, schema, mã trạng thái, SSE, web UI |
| 10 | [Cấu hình & vận hành](10-configuration-and-operations.md) | Biến môi trường, YAML, Makefile, Docker, CI, observability |
| 11 | [Kiểm thử](11-testing.md) | Chiến lược test, từng file test, cách chạy, cách viết test mới |
| 12 | [Thuật ngữ](12-glossary.md) | Thuật ngữ AI/IR/NLI và pháp luật dùng trong dự án |
| 13 | [Giới hạn & lệch tài liệu](13-known-gaps.md) | Hạn chế đã biết, lỗi còn tồn, chỗ tài liệu cũ không còn khớp code |
| 14 | [Cách mở rộng](14-how-to-extend.md) | Công thức cho việc thường gặp: thêm provider, config, văn bản, metric… |

## Dự án trong một hình

```
                       ┌──────────── OFFLINE: ingest (idempotent) ────────────┐
 data/corpus/*.md ──►  loaders ──► chunkers ──► embedder (bge-m3) + BM25 ──► Qdrant
                       └──────────────────────────────────────────────────────┘

                       ┌──────────────── ONLINE: một câu hỏi ─────────────────┐
 POST /chat ──► retrieve: dense + BM25 → RRF → rerank → [agentic: viết lại]
                   │
                   ├── không đoạn nào ≥ min_score ──────────────► no_context
                   ▼
               LLM (bắt buộc trích dẫn [C1]…) ── tự từ chối ──► abstained (model)
                   │
               gỡ trích dẫn bịa → tách mệnh đề → NLI từng mệnh đề
                   │
               policy: trả lời │ sinh lại 1 lần │ bỏ mệnh đề │ từ chối
                   ▼
               Answer {answer, status, claims, sources, meta.steps}
                       └──────────────────────────────────────────────────────┘
```

## Ba câu để nhớ

1. **Đây là RAG có kiểm chứng**: mỗi câu trong câu trả lời được đối chiếu với đúng
   đoạn luật nó trích dẫn trước khi tới người dùng; không đủ căn cứ thì từ chối.
2. **Phần đáng giá nhất là đo lường**: benchmark 100 câu, 40% không có đáp án,
   bốn cấu hình chấm bằng cùng một thước đo.
3. **Kết luận trung thực**: model NLI không bắt được các lỗi thật của generator
   trên tập dev; thứ bảo vệ câu trả lời là các lớp rẻ (ngưỡng retrieval, luật con
   số, kiểm tra trích dẫn).

---

[Mục lục tài liệu dự án](../README.md)
