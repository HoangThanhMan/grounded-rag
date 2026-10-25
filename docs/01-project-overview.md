# 01 — Tổng quan dự án

## Một câu

RAG service trả lời câu hỏi trên tập văn bản pháp luật tiếng Việt; mỗi mệnh đề
trong câu trả lời được máy đối chiếu lại với đúng đoạn tài liệu mà nó trích dẫn
trước khi tới người dùng, và hệ thống từ chối trả lời khi không đủ căn cứ.

## Vấn đề

RAG chuẩn vẫn bịa. Ba tình huống hay gặp nhất:

1. **Retrieval trả về đoạn không liên quan** → model vẫn cố trả lời từ đoạn sai.
2. **Câu hỏi không có đáp án trong tài liệu** → model dùng kiến thức pretrain,
   người đọc tưởng đó là nội dung tài liệu.
3. **Câu trả lời trộn lẫn** → 3 câu đúng theo tài liệu, câu thứ 4 là suy diễn.
   Không ai phát hiện vì phần lớn câu trả lời trông hợp lý.

Trong domain pháp lý, một câu suy diễn nghe hợp lý nguy hiểm hơn một câu sai
lộ liễu. Và điều đáng nói là: **phần lớn demo RAG không hề đo lường chuyện này.**

## Giải pháp

Hai thành phần thêm vào pipeline RAG thông thường:

- **Groundedness guard** — tách câu trả lời thành mệnh đề, kiểm chứng từng mệnh
  đề với đoạn nó trích dẫn bằng model NLI chạy tại chỗ. Xem [06](06-guard-design.md).
- **Bộ đo lường** — 100 câu hỏi tự gán nhãn, 40 câu cố tình không có đáp án.
  Chạy được bằng một lệnh, chạy tự động trong CI. Xem [07](07-evaluation-plan.md).

## Đo thành công bằng gì

Dự án coi là thành công khi README có bảng này với **số thật**:

| Cấu hình | Halluc. ↓ | Correct abst. ↑ | False abst. ↓ | p95 (ms) |
|---|---|---|---|---|
| baseline (không guard) | | | | |
| threshold (ngưỡng retrieval) | | | | |
| full (guard đầy đủ) | | | | |
| agentic (full + truy xuất sửa lỗi) | | | | |

Không phải "chạy được", mà là "đo được và số liệu nói lên điều gì đó". Dòng
`agentic` là phần mở rộng, không phải điều kiện thành công: lõi vẫn là guard.

> Nếu guard **không** cải thiện được số liệu, đó vẫn là kết quả có giá trị.
> Báo cáo trung thực kèm phân tích nguyên nhân. Không chỉnh số.

## Bối cảnh

Dự án cá nhân, làm một mình trong 3 tuần. Nối tiếp luận văn về phát hiện hallucination trong dịch máy —
cùng một câu hỏi (làm sao biết model đang bịa?), đặt trong bối cảnh RAG.

## Không phải mục tiêu

Xem [02 — Yêu cầu](02-requirements.md), mục "Ngoài phạm vi". Danh sách những
thứ **cố tình không làm** quan trọng ngang danh sách những thứ sẽ làm.
