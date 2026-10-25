# Hướng dẫn gán nhãn tập đánh giá

Tập đánh giá là phần quan trọng nhất của dự án. Số liệu trong README chỉ đáng
tin bằng đúng chất lượng của tập này, nên quy trình dưới đây phải làm nghiêm.

## Mục tiêu

v2: 300 câu, chia như sau:

| Loại | Số câu | Ý nghĩa |
|---|---|---|
| `answerable` | 180 | Có đáp án rõ ràng trong corpus |
| `unanswerable_out_of_scope` | 40 | Nội dung thuộc văn bản pháp luật khác |
| `unanswerable_false_premise` | 40 | Giả định một quy định không tồn tại |
| `unanswerable_near_miss` | 40 | Đúng chủ đề, đúng thuật ngữ, nhưng chi tiết không có trong văn bản |

`near_miss` là loại khó nhất và cũng là loại model bịa nhiều nhất. Đừng cắt
loại này khi thiếu thời gian — cắt bớt `out_of_scope` trước.

Tag: `multi_part` (hỏi hai ý trở lên, gold gồm nhiều khoản), `colloquial` (nói
kiểu đời thường: "nghỉ việc", "nghỉ phép" thay cho thuật ngữ luật), `temporal`
(đáp án khác nhau theo ngày hỏi, xem bên dưới). Ít nhất 20 câu `temporal`.

Chia **dev 60 / test 240** theo nhóm điều luật (`article_group`): câu có gold
thuộc cùng một Điều nằm cùng một split, để τ không bao giờ được hiệu chỉnh trên
đúng điều mà một câu test được chấm. Dev gồm 42 `answerable` và 6 câu mỗi loại
không trả lời được — không theo tỉ lệ, vì 20 câu dev của v1 phải ở lại dev (τ đã
hiệu chỉnh trên chúng) và nhóm điều của chúng đã chứa 42 câu trả lời được. Nhóm
và split do `scripts/assemble_dataset.py` tính, không sửa tay.

## Quy trình

1. **Sinh câu hỏi ứng viên.** Ba nguồn, đều chỉ là nguyên liệu thô:
   - LLM sinh 2 câu hỏi từ mỗi chunk (v1, `source: chunk_generated`).
   - Câu hỏi người thật của **TVPL-Retrieval-VN** (GreenNode trên Hugging Face,
     **CC-BY-SA-4.0**, `source: tvpl`): `scripts/import_candidates.py` chỉ giữ
     câu có đoạn bằng chứng khớp nguyên văn một khoản của corpus và đề xuất khoản
     đó làm gold. Mỗi quyết định giữ / bỏ kèm lý do nằm ở `drafts/tvpl.jsonl`.
   - Câu tự viết (`source: handwritten`); một số câu `out_of_scope` lấy ý từ bộ
     Zalo AI Legal Text Retrieval (MIT, `source: zalo`). Bộ Zalo không có câu
     nào thuộc Bộ luật Lao động 2019 hay Luật BHXH.
   Bộ VLSP 2025 DRILL không dùng: phải đăng ký và không công bố license.
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
  "tags": ["colloquial"],
  "article_group": "bo_luat_lao_dong_2019:Điều 35 +1",
  "split": "test",
  "source": "tvpl",
  "source_id": "..."
}
```

Câu `temporal` có thêm `as_of` (ngày hỏi) và `temporal_pair` (tên cặp). Một
cặp là **cùng một câu hỏi** hỏi vào hai ngày, với hai đáp án khác nhau, và gold
của mỗi vế phải có hiệu lực vào ngày của vế đó. `eval.run` hỏi câu temporal
đúng vào `as_of` của nó; mọi câu khác dùng `--as-of` của lượt chạy.

`gold_chunks` ghi theo `ref`: `<doc_id>:Điều <số>:<số khoản>`, hoặc
`<doc_id>:Điều <số>` nếu điều đó không chia khoản. `doc_id` là tên file không
đuôi. Eval tự tra ra nội dung khoản, nên chunk `recursive` cũng được chấm công
bằng.

## Câu temporal và Luật BHXH 2014

Corpus có thêm Luật BHXH 2014 (`luat_bao_hiem_xa_hoi_2014`, hiệu lực
01/01/2016 – trước 01/07/2025) để hỏi cùng một câu trước và sau Luật BHXH 2024.
Hiệu lực chỉ áp ở cấp văn bản (B7), mà Luật 2014 đã bị sửa nhiều lần, nên một
câu temporal chỉ được dựa vào điều **chưa bị sửa** từ 2016 đến 2025. Tám điều
đang dùng — 29, 32, 33, 34, 38, 41, 66, 68 — đều:

- không có chú thích sửa đổi trong Văn bản hợp nhất 50/VBHN-VPQH (2018), và
  không nằm trong các điều mà Điều 219 Bộ luật Lao động 2019 sửa (54, 55, 73);
- được đối chiếu từng chữ với bản quét Công báo (trang 13–18, 27–29).

Bản toàn văn lấy từ một trang web (bản quét chính thức không có lớp chữ) và
mất số thứ tự khoản, nên gold của Luật 2014 ghi ở cấp điều (`…:Điều 32`).

## Đồng thuận gán nhãn

`scripts/agreement.py sample` rút 60 câu phân tầng theo loại thành sheet "mù"
(`agreement/relabel.json`, chỉ có câu hỏi). Gán lại loại và điều gold mà
không mở `questions.jsonl` — do người thứ hai (`inter`), hoặc chính người gán
nhãn sau ít nhất 10 ngày (`intra`; `score` từ chối chấm sớm hơn). `score` báo
Cohen's κ cho loại câu và cho trả lời được / không; mục tiêu κ ≥ 0.7. Báo cáo
phải ghi rõ đó là intra- hay inter-annotator.

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

### 2026-09-17 — kiểm tra chéo lần hai

Đọc lại cả 100 câu cạnh nguyên văn khoản gold, tìm toàn văn corpus cho các câu
không trả lời được. Lượt này do trợ lý AI làm, không phải
người gán nhãn ban đầu — một cặp mắt khác, nhưng không phải chuyên gia pháp lý.
Sửa 4/100 câu, trong khoảng 5–10% mà bước 6 dự kiến. Cả ba câu đổi loại lại
rơi đúng vào cái bẫy của quy tắc 5, dù lần một đã biết cái bẫy đó:

| Trước | Sau | Lý do |
|---|---|---|
| u021 `false_premise` — nghỉ không báo trước "bị phạt bao nhiêu tiền" | a061 `answerable`, Điều 40:2 | Luật không phạt tiền, nhưng quy định rõ khoản bồi thường. Bác tiền đề kèm trích dẫn là câu trả lời đúng |
| u029 `false_premise` — lộ thông tin nội bộ "phạt bao nhiêu tháng lương" | a062 `answerable`, Điều 127:2 | Cùng khuôn với a020: phạt tiền thay kỷ luật bị cấm |
| u040 `near_miss` — sinh con lần thứ ba nghỉ thai sản bao lâu | a063 `answerable`, Điều 139:1 | "06 tháng" không phụ thuộc con thứ mấy; corpus trả lời được |
| a026 tag `colloquial` | bỏ tag | Câu dùng đúng thuật ngữ "nghỉ hằng năm" |

Id mới giữ `relabelled_from` để đối chiếu với report cũ. Tập nay là 63
`answerable`, 15 `out_of_scope`, 13 `false_premise`, 9 `near_miss`; 11 câu
`colloquial`, 11 câu `multi_part`. Mọi report trước ngày này dùng nhãn cũ và
không so trực tiếp được.

Giữ nguyên, sau khi cân nhắc: u028 ("làm việc tối thiểu bao nhiêu năm mới được
ký hợp đồng không xác định thời hạn") — Điều 20 không đặt điều kiện thâm niên
nào, và không có khoản nào bác tiền đề trực tiếp như Điều 127:2.

### 2026-09-17 — tách tập dev

20 câu có `"split": "dev"`, lấy phân tầng (câu thứ 5, 10, ... trong mỗi loại
theo thứ tự ban đầu). Chỉ dùng để hiệu chỉnh τ (`scripts/calibrate_tau.py`);
`eval.run` mặc định chấm trên 80 câu `test` còn lại.

### 2026-10-26 — v2: 300 câu

`questions.jsonl` từ 100 lên 300 câu theo spec v2 (WS1a): 180 `answerable`,
40 mỗi loại không trả lời được; 44 `colloquial`, 18 `multi_part`, 20
`temporal`. 100 câu v1 giữ nguyên id, nhãn và gold. Dựng bằng
`scripts/assemble_dataset.py` từ ba bản nháp trong `drafts/`.

- **93 câu từ TVPL-Retrieval-VN** (197 ứng viên, giữ 93). Mỗi câu được viết
  lại theo corpus, gold thu hẹp đúng khoản trả lời. 104 câu bỏ, mỗi câu một lý
  do: trùng câu đã có, công chức hoặc lực lượng vũ trang (ngoài phạm vi), luật
  không trả lời trực tiếp, hoặc quá chung. Chỉ 3 câu thuộc Luật BHXH 2024 — bộ
  TVPL có trước luật này.
- **10 cặp temporal** trên Luật BHXH 2014 / 2024, hỏi vào 2024-06-01 và
  2025-09-01. Bốn cặp dùng lại câu v1 làm vế hiện hành (a052, a053, a055, a057:
  chỉ thêm `as_of`, tag và cặp; nhãn không đổi).
- **8 câu viết tay** về Luật BHXH 2024, bù phần TVPL thiếu.
- **83 câu không trả lời được**, viết tay, tìm toàn văn từng câu. Năm câu nháp
  bị thay trước khi vào tập vì rơi đúng bẫy quy tắc 5 — luật có khoản bác tiền
  đề: thưởng chuyên cần và tăng lương khi ký lại (Điều 103, 104), "Nhà nước tặng
  năm đóng BHXH tự nguyện" (Điều 6 khoản 6 Luật BHXH 2024 nói hỗ trợ *tiền
  đóng*), thưởng thâm niên (Điều 114), tỉ lệ người lao động yêu cầu đối thoại
  (Điều 63 khoản 2: chỉ cần yêu cầu của một bên).
- **`multi_part` chỉ gắn khi gold có từ hai khoản.** Câu hỏi danh sách nằm gọn
  trong một khoản (các ngày nghỉ lễ, nghĩa vụ của người lao động) không gắn.
- Cảnh báo còn lại của `check_dataset.py` đã đọc tay: u018 (như trên); u043
  ("ký quỹ đi làm việc ở nước ngoài") khớp Điều 85 Luật BHXH 2014, nhưng điều
  đó nói về mức đóng bảo hiểm, không về ký quỹ — giữ nhãn.

Tập test đổi hoàn toàn: mọi report trước ngày này chấm trên 80 câu test v1 và
không so trực tiếp được với report v2. τ = 0.50 vẫn là ngưỡng hiệu chỉnh trên
20 câu dev v1, nay nằm trong dev v2.
