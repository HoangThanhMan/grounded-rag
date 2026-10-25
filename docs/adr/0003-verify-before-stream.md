# ADR-0003 — Kiểm chứng xong mới stream

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-08

## Bối cảnh

Stream token khi model đang sinh cho cảm giác nhanh. Nhưng guard chỉ chạy được
khi đã có câu trả lời đầy đủ — không thể kiểm chứng một câu chưa viết xong.

Ba lựa chọn:

1. Stream ngay, kiểm chứng sau, thu hồi nếu sai
2. Kiểm chứng xong mới stream
3. Stream theo từng mệnh đề, kiểm chứng mệnh đề nào xong mệnh đề đó

## Quyết định

Phương án 2 làm mặc định. Có cờ `stream_unverified=true` để so sánh trải nghiệm.

## Lý do

Phương án 1 thất bại ở đúng chỗ dự án này quan tâm: **người dùng đã đọc câu sai
trước khi nó bị thu hồi.** Với một người không đủ chuyên môn tự kiểm chứng —
đúng người dùng giả định ở [docs 02](../02-requirements.md) — thông tin sai đã
đọc rồi thì việc gạch nó đi không xoá được ấn tượng.

Phương án 3 hấp dẫn nhưng phức tạp hơn nhiều: phải phát hiện ranh giới mệnh đề
trên luồng token chưa hoàn chỉnh, xử lý mệnh đề bị guard chặn ở giữa. Không
xứng với ngân sách 3 tuần.

## Đánh đổi chấp nhận

- Người dùng đợi lâu hơn, ~1–2s cho bước verify
- Mất cảm giác "đang chạy" — bù bằng cách gửi sự kiện tiến trình
  (`retrieving` → `generating` → `verifying`) trước sự kiện `claim` đầu tiên

## Ghi chú

Phản biện dễ gặp nhất với thiết kế này là "sao không stream?". Câu trả lời
không phải "vì khó" mà là "vì với người dùng này, đúng quan trọng hơn nhanh, và
có cờ để đo cả hai."
