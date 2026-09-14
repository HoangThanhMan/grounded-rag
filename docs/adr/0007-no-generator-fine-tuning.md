# ADR-0007 — Không fine-tune model sinh; model mở chạy qua giao thức OpenAI

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-11

## Bối cảnh

Tài liệu tham khảo đề xuất fine-tune Llama/Qwen cho văn phong pháp lý tiếng
Việt bằng Unsloth (QLoRA, Quantization-Aware Training), rồi phục vụ bằng vLLM,
để tránh phụ thuộc API thương mại.

## Quyết định

1. **Không fine-tune model sinh** trong phạm vi hiện tại.
2. **Model mở được hỗ trợ đầy đủ** qua provider `vllm` và `ollama`. Cả hai nói
   giao thức OpenAI chat-completions, dùng chung `OpenAICompatClient`.
   `docker-compose.yml` có service `vllm` (profile `gpu`) chạy
   `Qwen2.5-7B-Instruct-AWQ`, trọng số đã lượng tử hoá 4-bit sẵn.

## Lý do

**Fine-tune model sinh đi ngược mục tiêu của dự án.** Huấn luyện trên cặp
hỏi–đáp pháp luật dạy model trả lời *từ trí nhớ*. Khi retrieval trượt, model đã
học thuộc sẽ trả lời tự tin bằng kiến thức trong tham số — đúng loại bịa mà
guard được xây để chặn, và nhiều nhất ở câu `near_miss` / `false_premise`. Kiến
thức trong tham số còn lỗi thời khi luật thay đổi: không lọc `as_of` được.

Các lý do còn lại:

- Yêu cầu N4 (chạy không cần GPU) và ngân sách 0 đồng; máy phát triển không có GPU.
- Thứ fine-tune mang lại (văn phong, tuân thủ định dạng trích dẫn) rẻ hơn nhiều
  khi xử lý bằng prompt và guard. Chưa có số liệu nào cho thấy model sinh là
  nút thắt.
- QAT chỉ có nghĩa khi *mình* huấn luyện. Dùng model có sẵn thì lấy trọng số đã
  lượng tử hoá (AWQ cho vLLM, GGUF cho Ollama).
- Con số "QAT phục hồi 70% độ chính xác" trong tài liệu tham khảo không có
  nguồn kiểm chứng, nên không trích dẫn.

## Nếu cần fine-tune, fine-tune cái gì

**NLI verifier**, không phải model sinh. mDeBERTa-v3 (~280M) trên ViNLI:
model nhỏ, huấn luyện được trên GPU miễn phí (Colab) trong vài giờ, tác động
thẳng vào chỉ số lõi (`hallucination_rate`, `false_abstention`). Đây vốn là
phương án dự phòng ở ngày 9 của roadmap.

Điều kiện kích hoạt: kiểm tra tay 20 cặp cho thấy NLI yếu với tiếng Việt, hoặc
đường precision–recall của guard kém. Tín hiệu đầu tiên đã có: trong 11 cặp thử
(`scripts/nli_probe.py`), mệnh đề đổi chủ thể và mệnh đề near-miss đều lọt qua
guard ([08](../08-roadmap.md#tín-hiệu-sớm-cho-rủi-ro-ngày-9)).

## Khi nào đảo quyết định

Có GPU, và RAGAS cho thấy phần lớn lỗi là `generation_unfaithful` (tìm đúng tài
liệu nhưng model không bám theo) dù prompt đã được tối ưu và guard đã hiệu chỉnh.
Khi đó fine-tune để *bám tài liệu* — dữ liệu huấn luyện gồm cả câu phải từ
chối — chứ không phải để *nhớ luật*.
