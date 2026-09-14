# 04 — Thiết kế dữ liệu

## Corpus

| Văn bản | Số hiệu | Hiệu lực | Nguồn |
|---|---|---|---|
| Bộ luật Lao động 2019 | 45/2019/QH14 | 01/01/2021 | Công báo số 993 + 994, 26/12/2019 |
| Luật Bảo hiểm xã hội 2024 | 41/2024/QH15 | 01/07/2025 | Công báo số 987 + 988, 25/8/2024 |

`make corpus` (`scripts/prepare_corpus.py`) tải bản PDF Công báo, bỏ header và
số trang, nối các dòng bị ngắt, kiểm tra đủ Điều và số khoản liên tục, rồi ghi
`data/corpus/*.md` kèm front matter. Kết quả: 684 + 557 chunk `structural`.

- Đây là **bản gốc khi ban hành**; các lần sửa đổi sau đó chưa được hợp nhất.
- Luật BHXH 2014 (58/2014/QH13) hết hiệu lực từ 01/07/2025 nên không đưa vào.
  Muốn thêm để minh hoạ `as_of`, ghi `expiry_date: 2025-07-01`.
- Lệch đã biết: Điều 219 Bộ luật Lao động sửa đổi các luật khác và trích
  nguyên văn khoản của chúng, nên số khoản trong điều này không liên tục và
  `ref` của các chunk trong đó không đáng tin.

Vì sao chọn văn bản pháp luật:

- Công khai, không vướng bản quyền
- Cấu trúc Điều/Khoản/Điểm rõ → trích dẫn tự nhiên tới "Điều 35 khoản 1"
- Câu hỏi thực tế dễ nghĩ, dễ kiểm chứng đúng/sai
- **Dễ tạo câu hỏi không trả lời được** — hỏi nội dung thuộc luật khác
- Là domain mà "thà không trả lời còn hơn trả lời sai" hiển nhiên đúng

Đặt file vào `data/corpus/`. Thư mục này không commit (xem `.gitignore`);
`scripts/fetch_corpus.sh` ghi lại nguồn tải.

### Metadata văn bản

Đầu mỗi file `.md`/`.txt` là front matter YAML (PDF: file `<tên>.meta.yaml`
đặt cạnh):

```yaml
---
title: Bộ luật Lao động 2019
number: 45/2019/QH14
issued_by: Quốc hội
effective_date: 2021-01-01
expiry_date:            # để trống = còn hiệu lực
---
```

`effective_date` / `expiry_date` được đóng lên từng chunk. Truy vấn mang ngày
`as_of` (mặc định hôm nay); chunk của văn bản chưa có hoặc đã hết hiệu lực vào
ngày đó không bao giờ được truy xuất. Với pháp luật, một điều khoản đã hết hiệu
lực là câu trả lời **sai**, không phải câu trả lời cũ. Ví dụ điển hình: Bộ luật
Lao động 2012 và 2019 cùng nằm trong corpus.

## Chunk

```python
class Chunk:
    chunk_id: str               # "<doc_id>:<sha256[:16]>" - content-addressed
    doc_id: str                 # "bo_luat_lao_dong_2019"
    text: str                   # "Điều 35. <tiêu đề>\n1. <nội dung khoản>"
    article: str | None         # "Điều 35"
    clause: str | None          # "Khoản 1"
    chapter: str | None         # "Chương III"
    doc_title: str | None
    effective_date: date | None
    expiry_date: date | None
    page: int | None
    lang: str = "vi"

    ref: str                    # computed: "bo_luat_lao_dong_2019:Điều 35:1"
```

`ref` là địa chỉ người đọc hiểu được, cũng là định dạng của `gold_chunks` trong
tập đánh giá.

**`chunk_id` là hash nội dung**, không phải số thứ tự. Hệ quả: ingest lại cùng
một tài liệu ghi đè đúng chỗ cũ thay vì tạo bản sao. Đây là lý do `make ingest`
an toàn khi chạy nhiều lần — một tính chất nhỏ nhưng tiết kiệm rất nhiều thời
gian debug về sau.

## Hai chiến lược chunk

| | `recursive` | `structural` |
|---|---|---|
| Cách cắt | Theo đoạn/câu, giới hạn 1200 ký tự | Theo ranh giới Điều → Khoản |
| Ưu | Dùng được cho mọi loại văn bản | Trích dẫn trỏ đúng khoản luật |
| Nhược | Trích dẫn trỏ vào cửa sổ tuỳ ý | Chỉ đúng với văn bản có cấu trúc |
| Dùng khi | baseline | full |

Cả hai được so sánh trong eval — đây là một dòng trong bảng kết quả, không phải
lựa chọn cảm tính. Xem [ADR-0004](adr/0004-structural-chunking.md).

`structural_chunk()` tự động lùi về `recursive_chunk()` khi không tìm thấy
"Điều" nào, nên nó không bao giờ trả về danh sách rỗng.

Chunk `structural` **mang tiêu đề Điều** ở dòng đầu. Khoản 2 của Điều 35 tự nó
chỉ nói "không phải báo trước trong trường hợp…"; có tiêu đề thì cả retriever
lẫn premise của NLI đều biết nó nói về chuyện gì. Khoản quá dài bị cắt nhỏ thì
mảnh nào cũng giữ tiêu đề. Dòng "Chương …" / "Mục …" đóng Điều trước nó lại
(không lẫn vào khoản cuối) và thành metadata `chapter`. Dấu `.` hoặc `:` sau số
Điều là bắt buộc, để một dòng bị ngắt giữa câu bắt đầu bằng "Điều 35 của Bộ luật
này…" không bị tưởng là Điều mới.

## Lưu trữ trong Qdrant

Mỗi chunker một collection — `grounded_rag_structural`, `grounded_rag_recursive`
— vì hai chiến lược là hai chỉ mục khác nhau của cùng corpus và không được trộn.

```
point_id : uuid5(chunk_id)          # ổn định qua các lần ingest
vectors  : { "dense":  bge-m3, cosine
             "sparse": BM25 term frequency; Qdrant áp IDF (Modifier.IDF) }
payload  : chunk.model_dump() + ingested_at
           (chunk_id, doc_id, text, article, clause, chapter, doc_title,
            effective_date, expiry_date, ref, ...)
```

Lọc hiệu lực chạy trong Qdrant: `effective_date` trống hoặc ≤ `as_of`, và
`expiry_date` trống hoặc > `as_of`.

Ingest chỉ embed chunk mới (kiểm tra `point_id` đã có chưa), nên ingest lại
corpus không đổi thì gần như không tốn gì. Đổi chunker thì chạy
`--recreate` để chunk cũ không nằm lẫn với chunk mới.

Index: HNSW mặc định (`m=16`, `ef_construct=100`). Với corpus vài nghìn chunk
thì tham số mặc định là đủ; chỉ tune khi có số liệu cho thấy cần.

Payload lưu cả `text` để không phải truy ngược về file gốc khi dựng prompt.

## Tập đánh giá

```json
{
  "id": "a001",
  "question": "...",
  "answerable": true,
  "gold_answer": "Ít nhất 45 ngày.",
  "gold_chunks": ["bo_luat_lao_dong_2019:Điều 35:1"],
  "type": "answerable",
  "tags": ["colloquial"]
}
```

`type` ∈ `answerable` | `unanswerable_out_of_scope` | `unanswerable_false_premise`
| `unanswerable_near_miss`

`tags` (không bắt buộc) đánh dấu lát cắt cần báo cáo riêng: `multi_part` (câu
hỏi nhiều ý), `colloquial` (cách nói đời thường, không dùng thuật ngữ luật).

`gold_chunks` ghi theo `ref`. Khi chấm, một chunk được coi là trúng gold nếu
`ref` khớp, **hoặc** nó chứa khoản gold — trọn khoản, hoặc một nửa của khoản
dài bị ranh giới cửa sổ cắt ngang (docs/07). Điều kiện thứ hai giúp chunk
`recursive` (không có `ref` theo khoản) được chấm công bằng như chunk
`structural`.

Quy trình gán nhãn: [eval/dataset/LABELING.md](../eval/dataset/LABELING.md).

## Vòng đời dữ liệu

```
file → load → chunk → embed → upsert(Qdrant)     [offline, idempotent]
query → search → rerank → prompt → answer         [online, không ghi gì]
```

Đường online **không ghi vào chỉ mục**. Không có vòng phản hồi tự động từ câu
trả lời trở lại corpus — nếu có, một lần bịa sẽ trở thành nguồn cho lần sau.
