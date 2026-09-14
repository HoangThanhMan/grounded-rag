# ADR-0002 — Qdrant làm vector store

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-08

## Bối cảnh

Cần lưu vài nghìn chunk có metadata, tìm kiếm hybrid (dense + sparse), chạy
local, không tốn tiền.

## Quyết định

Qdrant, chạy bằng Docker, dùng named vectors cho dense và sparse.

## Lý do

- Hỗ trợ **named vectors** trong một collection → dense và sparse cùng một
  point, hybrid search không cần hai hệ thống
- Chạy local bằng một dòng compose, không cần tài khoản cloud
- Filter theo payload nhanh, hữu ích khi mở rộng sang nhiều tài liệu
- Đã dùng ở dự án trước → không tốn thời gian học lại

## Phương án bị loại

| Phương án | Vì sao loại |
|---|---|
| Chroma | Đơn giản hơn nhưng hỗ trợ sparse/hybrid yếu |
| FAISS | Nhanh nhưng không có metadata filter, phải tự quản lý mapping |
| pgvector | Tốt nếu đã có Postgres; ở đây thêm một service không cần thiết |
| Pinecone | Cloud, cần tài khoản, ngược yêu cầu "chạy được offline" |

## Hệ quả

- `InMemoryStore` vẫn được giữ cho provider `mock`, để test và CI không cần
  container nào. Hai cài đặt cùng một protocol `VectorStore`.
