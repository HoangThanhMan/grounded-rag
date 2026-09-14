# 06 — Thiết kế groundedness guard

Đây là phần lõi của dự án. Mọi thứ khác là RAG bình thường.

## Ý tưởng

Một câu trả lời RAG đúng là câu trả lời mà **mọi khẳng định trong đó đều suy ra
được từ đoạn tài liệu mà nó viện dẫn**. Đó chính là định nghĩa của quan hệ
*entailment* trong NLI. Vậy nên bài toán "phát hiện bịa" được đưa về một bài
toán NLI đã có model sẵn.

```
premise    = nội dung đoạn tài liệu được trích dẫn
hypothesis = mệnh đề trong câu trả lời
score      = P(entailment)
```

## Bốn bước

### 1. Tách mệnh đề — `claim_splitter.py`

Cắt câu trả lời thành từng câu, mỗi câu mang theo mã trích dẫn của nó.

Cái bẫy: tiếng Việt pháp lý có dấu chấm không kết thúc câu — "Điều 35.",
"khoản 1.", "NĐ 145.". Module bảo vệ các token này (không phân biệt hoa thường)
trước khi cắt, rồi khôi phục. Danh sách token nằm ở `_PROTECTED`, phải cập nhật
khi đổi corpus.

Hai cái bẫy nữa, đến từ cách LLM viết chứ không phải từ văn bản luật:

- **Trích dẫn đặt sau dấu chấm:** "Câu một. [C1] Câu hai." — nếu cắt thẳng thì
  `[C1]` thuộc về câu hai. Mã trích dẫn được đưa vào trong câu trước khi cắt.
- **Trả lời dạng danh sách:** mỗi dòng là ít nhất một mệnh đề; ký hiệu đầu dòng
  (`1.`, `-`, `•`) bị bỏ; mảnh không có chữ nào không phải là mệnh đề.

Có unit test riêng cho từng trường hợp (`test_claim_splitter.py`).

### 2. Kiểm chứng — `nli_verifier.py`

Model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`

- Đa ngữ, có tiếng Việt trong tập huấn luyện
- ~280M tham số → chạy được trên CPU
- Cache theo `sha256(premise || hypothesis)`; trong eval, cùng một cặp lặp lại
  rất nhiều nên cache tiết kiệm đáng kể

Mệnh đề trích dẫn nhiều đoạn thì premise là các đoạn nối lại.

### 3. Chính sách — `policy.py`

| Tình huống | Hành động |
|---|---|
| Mọi mệnh đề `≥ τ` | Trả lời, `status: answered` |
| Có mệnh đề `< τ`, chưa sinh lại | Sinh lại 1 lần kèm phản hồi cụ thể |
| Sau sinh lại vẫn còn mệnh đề `< τ`, còn mệnh đề tốt | Bỏ mệnh đề xấu, `status: partial` |
| Không còn mệnh đề nào tốt | Từ chối, `status: abstained`, `abstain_reason: guard` |
| Mệnh đề không có trích dẫn | `verdict: uncited` — luôn bị coi là không có căn cứ |
| Model trả đúng câu từ chối của prompt | `status: abstained`, `abstain_reason: model` — không kiểm chứng, **không sinh lại** |

Dòng cuối quan trọng hơn vẻ ngoài của nó. Câu từ chối không có mã trích dẫn nên
trước đây bị coi là mệnh đề `uncited`: guard sinh lại vô ích, còn baseline bị
tính là "trả lời và bịa" đúng lúc nó từ chối đúng.

Phản hồi khi sinh lại nêu đích danh mệnh đề có vấn đề, không phải lời nhắc
chung chung:

```
Câu trả lời trước có những mệnh đề KHÔNG được tài liệu chứng minh:
- Người lao động được thưởng thêm 10% lương.
Hãy viết lại, chỉ dùng thông tin có trong tài liệu được cung cấp.
```

### 4. Hiệu chỉnh ngưỡng τ

**τ không được chọn bừa.** Quy trình:

1. Tách 20 câu từ tập đánh giá làm tập dev (không dùng lại khi báo cáo)
2. Chạy pipeline, thu điểm entailment của từng mệnh đề
3. Gán nhãn thủ công từng mệnh đề: có căn cứ / không có căn cứ
4. Quét τ từ 0.1 đến 0.9, vẽ precision–recall của guard
5. Chọn τ tại điểm mà `false_abstention` còn dưới 15%

Đường cong này **phải có trong README**. Nó là bằng chứng phân biệt người làm
kỹ với người ghép thư viện.

## Guard sai ở đâu

Biết giới hạn của giải pháp mình làm quan trọng ngang việc làm ra nó.

| Loại lỗi | Vì sao | Xử lý |
|---|---|---|
| Mệnh đề đúng, cần suy luận nhiều bước | NLI cho `neutral` | Chấp nhận, tính vào `false_abstention` |
| Mệnh đề đúng nhưng diễn đạt lại xa nguyên văn | NLI yếu với paraphrase dài | Prompt yêu cầu bám sát từ ngữ tài liệu |
| Mệnh đề tổng hợp từ nhiều đoạn | Premise ghép có thể nhiễu | Chấp nhận; ghi nhận trong phần hạn chế |
| NLI đa ngữ yếu với tiếng Việt | Model huấn luyện chủ yếu trên XNLI | Kiểm tra sớm ở ngày 9 trên 20 cặp thủ công (`scripts/nli_probe.py`) |
| **Mệnh đề giữ gần hết từ ngữ nhưng đổi chủ thể hoặc thêm điều kiện** | NLI thiên về trùng từ vựng. Thử 11 cặp: đổi chủ thể 0.84, "thử việc" 0.73 — cả hai lọt qua τ = 0.60 ([08](08-roadmap.md#tín-hiệu-sớm-cho-rủi-ro-ngày-9)) | Model NLI lớn hơn, fine-tune ViNLI ([ADR-0007](adr/0007-no-generator-fine-tuning.md)); đo riêng `by_type.unanswerable_near_miss` |

**Chi phí của guard là `false_abstention`** — từ chối nhầm câu trả lời được.
Đây là chỉ số bắt buộc báo cáo cùng `hallucination_rate`. Một guard chặn 100%
câu bịa bằng cách từ chối mọi thứ là guard vô dụng, và bảng số liệu phải cho
thấy được điều đó.

## Vì sao không dùng LLM để chấm

Xem [ADR-0001](adr/0001-nli-over-llm-judge.md).
