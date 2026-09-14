# ADR-0001 — Dùng model NLI thay vì LLM-as-judge để kiểm chứng

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-08

## Bối cảnh

Cần kiểm tra: mệnh đề X có được suy ra từ đoạn tài liệu Y không. Hai hướng phổ
biến — gọi một LLM và hỏi nó, hoặc chạy một model NLI chuyên dụng.

## Quyết định

Dùng `mDeBERTa-v3-base-xnli` chạy tại chỗ, lấy `P(entailment)`.

## Lý do

| Tiêu chí | NLI self-hosted | LLM-as-judge |
|---|---|---|
| Chi phí | 0, chạy local | Một lần gọi API cho **mỗi mệnh đề** |
| Độ trễ | ~50–200ms trên CPU | 0.5–2s, phụ thuộc mạng |
| Tính tất định | Cùng input → cùng output | Trôi theo version model, nhiệt độ |
| Tính độc lập | Model khác họ với model sinh | Cùng họ lỗi, cùng thiên lệch |
| Diễn giải | Một con số, hiệu chỉnh ngưỡng được | Nhãn của một hộp đen |

Điểm quyết định là hàng "tính độc lập": dùng LLM chấm bài LLM nghĩa là dùng
đúng loại model đã bịa để phát hiện chính nó bịa. Cả hai chia sẻ cùng những
thiên lệch — thứ nghe hợp lý với model sinh cũng nghe hợp lý với model chấm.

## Đánh đổi chấp nhận

- NLI yếu hơn với mệnh đề cần suy luận nhiều bước → tính vào `false_abstention`
- NLI đa ngữ có thể yếu với tiếng Việt → **kiểm tra ở ngày 9, có phương án dự
  phòng** (`xlm-roberta-large-xnli`, hoặc fine-tune trên ViNLI)
- Thêm một model 280M phải tải và chạy

## Phương án bị loại

- **LLM-as-judge** — lý do ở bảng trên. Vẫn dùng nó ở một chỗ: đo đối chứng
  trong eval, để biết guard NLI tốt/xấu so với nó.
- **Đối sánh chuỗi / n-gram overlap** — quá thô, model chỉ cần diễn đạt lại là
  qua được.

## Liên quan

Tiền lệ trong dự án trước: thay LLM API bằng RoBERTa self-hosted cho phân loại
sentiment, giảm 229ms → 41ms mỗi bản tin. Cùng một lập luận, cùng một kết luận.
