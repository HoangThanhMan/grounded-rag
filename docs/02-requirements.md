# 02 — Yêu cầu

## Người dùng giả định

Một người cần tra cứu quy định lao động và **không đủ chuyên môn để phát hiện
câu trả lời sai**. Đây là giả định định hình toàn bộ thiết kế: nếu người dùng
tự kiểm chứng được thì guard không cần tồn tại.

## Yêu cầu chức năng

| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| F1 | Nạp tài liệu PDF/Markdown vào chỉ mục, chạy lại không tạo bản sao | Must |
| F2 | Trả lời câu hỏi kèm trích dẫn tới cấp Điều/Khoản | Must |
| F3 | Kiểm chứng từng mệnh đề với đoạn nó trích dẫn | Must |
| F4 | Từ chối trả lời khi không đủ căn cứ, thay vì đoán | Must |
| F5 | Phát hiện trích dẫn tới mã không tồn tại | Must |
| F6 | Sinh lại câu trả lời một lần khi guard phát hiện mệnh đề không có căn cứ | Should |
| F7 | Trả kết quả qua SSE | Should |
| F8 | Giao diện demo tô màu mệnh đề theo verdict | Should |
| F9 | Đổi provider LLM bằng config, không sửa code — gồm model mở qua vLLM/Ollama | Should |
| F10 | Ghi trace từng bước lên Langfuse | Could |
| F11 | Hybrid search: BM25 + dense | Must |
| F12 | Không truy xuất văn bản chưa có hoặc đã hết hiệu lực tại ngày `as_of` | Should |
| F13 | Truy xuất sửa lỗi có giới hạn (viết lại, tách câu hỏi) — một cấu hình riêng, đo riêng | Could |
| F14 | Mỗi câu trả lời mang trace, số lời gọi LLM, token, chi phí; `/metrics` cho Prometheus | Should |

## Yêu cầu phi chức năng

| ID | Yêu cầu | Ngưỡng |
|---|---|---|
| N1 | Độ trễ p95 (guard bật) | < 6s |
| N2 | Tỉ lệ bịa trên benchmark | < 10% |
| N3 | Tỉ lệ từ chối nhầm | < 15% |
| N4 | Chạy được không GPU | Bắt buộc |
| N5 | Chạy được không API key | Bắt buộc (provider `mock`) |
| N6 | `docker compose up` là chạy | Bắt buộc |

N4 và N5 quan trọng hơn vẻ ngoài của chúng: chúng khiến repo này ai clone về
cũng chạy được, kể cả người phỏng vấn.

## Ngoài phạm vi (cố tình)

- Multi-tenant, authentication, quản lý người dùng
- Kubernetes, autoscaling, load balancing
- Frontend hoàn chỉnh — Streamlit là đủ
- Định dạng ngoài PDF/Markdown
- Agent tự do (ReAct), tool calling, framework điều phối. Ngoại lệ duy nhất: một
  vòng truy xuất sửa lỗi có trần cứng, bật ở cấu hình riêng và đo riêng
  ([ADR-0005](adr/0005-corrective-retrieval-loop.md))
- Fine-tune model sinh ([ADR-0007](adr/0007-no-generator-fine-tuning.md)).
  Fine-tune NLI verifier trên ViNLI là phương án dự phòng, không phải mục tiêu

**Lý do:** với vị trí intern/fresher, một dự án sâu có số liệu thắng năm dự án
rộng không có số liệu. Mỗi mục trên đều tốn một tuần và không thêm được câu
chuyện phỏng vấn nào mà guard chưa có.

## Ràng buộc

- 3 tuần, một người, ~3h/ngày
- Chi phí LLM: 0 đồng (free tier hoặc Ollama local)
- Máy cá nhân, có thể không có GPU
