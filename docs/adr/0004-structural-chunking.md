# ADR-0004 — Chunk theo cấu trúc Điều/Khoản

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-08

## Bối cảnh

Chunking mặc định cắt theo số ký tự. Với văn bản pháp luật, cách đó cắt ngang
khoản luật, khiến trích dẫn trỏ vào một cửa sổ tuỳ ý thay vì một đơn vị có
nghĩa.

## Quyết định

Thêm `structural_chunk()`: cắt theo ranh giới `Điều` → `Khoản`, mỗi khoản là
một chunk, giữ `article` và `clause` trong metadata. Dùng cho cấu hình `full`.
Giữ `recursive_chunk()` cho `baseline` để so sánh.

## Lý do

- Trích dẫn trỏ tới "Điều 35, Khoản 1" — người đọc kiểm chứng được ngay
- Premise của NLI là một khoản trọn vẹn, không phải nửa câu → điểm entailment
  đáng tin hơn
- Metadata `article`/`clause` cho phép `gold_chunks` trong tập đánh giá được
  viết bằng ký hiệu người đọc hiểu được

## Đánh đổi chấp nhận

- Chỉ đúng với văn bản có cấu trúc điều khoản. Hàm tự lùi về `recursive` khi
  không tìm thấy "Điều" nào, nên không bao giờ trả về rỗng.
- Khoản quá dài vẫn phải cắt nhỏ → mất tính "một khoản một chunk" ở vài trường
  hợp
- Regex phụ thuộc cách trình bày của bản text. Đổi nguồn corpus phải kiểm tra
  lại `ARTICLE_RE` và `CLAUSE_RE`.

## Đo lường

Hai chunker được so sánh trong eval, chỉ số `citation_precision`. Nếu structural
không thắng, ADR này bị đảo và ghi lại lý do — quyết định này là giả thuyết cần
kiểm chứng, không phải niềm tin.
