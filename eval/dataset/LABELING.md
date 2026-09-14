# Hướng dẫn gán nhãn tập đánh giá

Tập đánh giá là phần quan trọng nhất của dự án. Số liệu trong README chỉ đáng
tin bằng đúng chất lượng của tập này, nên quy trình dưới đây phải làm nghiêm.

## Mục tiêu

100 câu hỏi, chia như sau:

| Loại | Số câu | Ý nghĩa |
|---|---|---|
| `answerable` | 60 | Có đáp án rõ ràng trong corpus |
| `unanswerable_out_of_scope` | 15 | Nội dung thuộc văn bản pháp luật khác |
| `unanswerable_false_premise` | 15 | Giả định một quy định không tồn tại |
| `unanswerable_near_miss` | 10 | Đúng chủ đề, đúng thuật ngữ, nhưng chi tiết không có trong văn bản |

`near_miss` là loại khó nhất và cũng là loại model bịa nhiều nhất. Đừng cắt
loại này khi thiếu thời gian — cắt bớt `out_of_scope` trước.

Trong 60 câu `answerable`, gắn `tags` cho khoảng 10 câu `multi_part` (hỏi hai ý
trở lên, gold gồm nhiều khoản) và 10 câu `colloquial` (nói kiểu đời thường:
"nghỉ việc", "nghỉ phép" thay cho thuật ngữ luật). Hai lát cắt này là thứ cấu
hình `agentic` được đo trên.

## Quy trình

1. **Sinh câu hỏi ứng viên.** Với mỗi chunk, nhờ LLM sinh 2 câu hỏi mà chunk
   đó trả lời được. Đây chỉ là nguyên liệu thô. Có thể lấy thêm ứng viên từ các
   bộ Hỏi–Đáp pháp luật trên Hugging Face, nhưng chỉ giữ câu có đáp án nằm trong
   corpus, và duyệt như câu sinh máy.
2. **Người duyệt.** Tự đọc lại từng câu. Loại bỏ câu mơ hồ, câu trả lời được
   bằng nhiều chunk khác nhau, câu chỉ hỏi lại nguyên văn tiêu đề điều luật.
3. **Ghi đáp án chuẩn** ngắn gọn, một đến hai câu, bằng lời của văn bản.
4. **Ghi `gold_chunks`** — danh sách `chunk_id` đủ để chứng minh đáp án. Nếu
   cần hai chunk thì ghi cả hai.
5. **Câu không trả lời được**: tự viết tay, không sinh máy. Kiểm tra bằng cách
   tìm kiếm toàn văn corpus để chắc chắn đáp án thực sự không tồn tại.
   Cẩn thận nhất với `false_premise`: luật hay *bác* đúng cái tiền đề sai. Câu
   mẫu "mức phạt khi đi làm muộn quá 3 lần" tưởng không có đáp án, nhưng Điều
   127 khoản 2 Bộ luật Lao động cấm "phạt tiền, cắt lương thay việc xử lý kỷ
   luật lao động" — câu trả lời tốt là bác tiền đề, không phải từ chối. Câu như
   vậy: hoặc bỏ khỏi nhóm unanswerable, hoặc chuyển sang `answerable` với gold
   là điều khoản bác tiền đề.
6. **Kiểm tra chéo lần hai** sau ít nhất một ngày. Tỉ lệ tự sửa lần hai thường
   khoảng 5–10%; nếu bằng 0 thì nhiều khả năng lần hai chưa đọc kỹ.

## Định dạng

Một dòng JSON mỗi câu, trong `eval/dataset/questions.jsonl`:

```json
{
  "id": "a001",
  "question": "...",
  "answerable": true,
  "gold_answer": "...",
  "gold_chunks": ["bo_luat_lao_dong_2019:Điều 35:1"],
  "type": "answerable",
  "tags": ["colloquial"]
}
```

`gold_chunks` ghi theo `ref`: `<doc_id>:Điều <số>:<số khoản>`, hoặc
`<doc_id>:Điều <số>` nếu điều đó không chia khoản. `doc_id` là tên file không
đuôi. Eval tự tra ra nội dung khoản, nên chunk `recursive` cũng được chấm công
bằng (docs/07).

## Quy tắc quan trọng

- **Không sửa tập đánh giá sau khi đã nhìn kết quả.** Nếu phải sửa (phát hiện
  nhãn sai), ghi lại trong `CHANGELOG` của file và chạy lại toàn bộ bốn cấu hình.
- Giữ `questions.sample.jsonl` (6 câu, có trong git) để CI chạy nhanh; tập đầy
  đủ nằm ở `questions.jsonl`.

## CHANGELOG

Mọi thay đổi nhãn sau khi tập đã dùng để chạy đều phải ghi ở đây, kèm lý do.

### 2026-09-14 — dựng tập 100 câu

`questions.jsonl`: 60 `answerable`, 15 `out_of_scope`, 15 `false_premise`,
10 `near_miss`. 12 câu gắn `colloquial`, 11 câu gắn `multi_part`.

Ba quyết định đáng ghi lại, tất cả đều theo quy tắc 5 ở trên — *luật hay bác
đúng cái tiền đề sai*:

1. **Hai câu chuyển từ "không trả lời được" sang `answerable`.** "Công ty bắt
   nộp phạt tiền khi đi làm muộn" và "phải đặt cọc bao nhiêu tiền khi ký hợp
   đồng" nghe như tiền đề sai, nhưng Điều 127 khoản 2 cấm phạt tiền thay xử lý
   kỷ luật, và Điều 17 khoản 2 cấm yêu cầu bảo đảm bằng tiền. Câu trả lời tốt
   là **bác tiền đề kèm trích dẫn**, không phải từ chối. Để ở nhóm unanswerable
   thì nhãn sẽ phạt đúng hành vi mà hệ thống nên có.

2. **Ba câu `near_miss` bị thay.** "Mức lương tối thiểu vùng I", "mức trợ cấp
   hưu trí xã hội hằng tháng", "mức tham chiếu" — cả ba hỏi một con số mà luật
   giao cho Chính phủ quy định. Corpus *có* trả lời phần "ai quyết định"
   (Điều 91 khoản 4, Điều 22 khoản 1 Luật BHXH), nên trả lời "do Chính phủ quy
   định [C1]" là đúng chứ không phải bịa — nhưng nhãn `unanswerable` sẽ tính
   đó là không từ chối. Thay bằng ba câu corpus im lặng hoàn toàn: thời hạn
   thông báo kết quả thử việc (Điều 27 khoản 1 bắt buộc thông báo nhưng không
   nêu thời hạn), thời hạn cam kết làm việc sau đào tạo (Điều 62 khoản 2 yêu
   cầu ghi nhưng không đặt trần), nghỉ việc riêng khi cháu ruột qua đời
   (Điều 115 không liệt kê quan hệ này).

3. **`gold_chunks` của câu "có mấy hình thức xử lý kỷ luật" ghi đủ bốn khoản**
   của Điều 124. Chunker cắt theo khoản nên ref `Điều 124` không tồn tại;
   `scripts/check_dataset.py` bắt được lỗi này.

Chạy `python scripts/check_dataset.py` sau mỗi lần sửa. Công cụ này giải ref
bằng đúng `ClauseIndex` mà eval dùng để chấm, đối chiếu từng con số trong
`gold_answer` với khoản được trích, và tìm toàn văn corpus cho các câu gắn nhãn
không trả lời được. Cảnh báo là lời nhắc đọc lại, không phải phán quyết:
cảnh báo còn lại ở u018 ("hợp đồng lao động phải công chứng trong bao nhiêu
ngày") đã đọc tay và giữ nguyên nhãn — Điều 14 chỉ quy định hình thức văn bản,
lời nói hoặc dữ liệu điện tử, và từ "công chứng" không xuất hiện lần nào trong
Bộ luật Lao động.

**Chưa làm: kiểm tra chéo lần hai** (quy trình bước 6) và **chấm tay 30 câu**.
Số liệu sinh ra từ tập này phải được đọc kèm hai điều đó.
