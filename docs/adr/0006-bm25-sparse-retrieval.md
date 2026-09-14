# ADR-0006 — BM25 cho nửa sparse của hybrid search

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-11

## Bối cảnh

Docs 03 bản đầu dự định dùng sparse vector của bge-m3 (lexical weights) cho
hybrid search. Bản cài đặt đầu tiên thật ra chỉ có dense (`# TODO` sparse). Tài
liệu tham khảo đề xuất BM25 để bắt chính xác thuật ngữ pháp lý.

## Quyết định

BM25, chạy ở hai nơi với cùng một công thức (`retrieval/lexical.py`):

- **Qdrant:** named sparse vector `"sparse"` với `Modifier.IDF`. Phía tài liệu
  lưu phần term frequency đã bão hoà của BM25 (`k1=1.2`, `b=0.75`); Qdrant tự
  tính IDF lúc truy vấn. Phía truy vấn: 1.0 cho mỗi token.
- **InMemoryStore** (provider `mock`): `BM25Index` thuần Python.

Tokenizer: âm tiết viết thường + bigram âm tiết liền kề (xấp xỉ tách từ tiếng
Việt, "hợp đồng" → `hợp_đồng`), số bỏ số 0 đứng đầu ("08 giờ" khớp "8 giờ").

## Lý do

- Câu hỏi pháp luật xoay quanh token chính xác — "Điều 35", "45 ngày",
  "48 giờ" — là thứ embedding làm nhoè đi.
- Không cần model, nên pipeline mock và CI có lexical retrieval thật thay vì
  hash ngẫu nhiên.
- Tất định, giải thích được bằng một công thức.
- Qdrant tự tính IDF, không phải tự duy trì thống kê toàn corpus.

## Phương án bị loại

| Phương án | Vì sao loại (lúc này) |
|---|---|
| Sparse vector bge-m3 | Cần thêm FlagEmbedding và một lần forward; learned sparse có thể tốt hơn BM25 nhưng chưa có số liệu. Là thí nghiệm hợp lý sau này |
| Tách từ bằng underthesea / pyvi | Thêm dependency; bigram âm tiết là xấp xỉ đủ dùng. Chỉ thêm khi đo được retrieval tốt hơn |
| Chỉ dense | Mất các khớp chính xác kể trên. Vẫn giữ được làm ablation: `hybrid: false` |

## Hệ quả

- `avg_len` (chuẩn hoá độ dài của BM25) tính trên lô ingest. Ingest tăng dần
  làm nó lệch nhẹ; đổi corpus lớn thì chạy `--recreate`.
- Mỗi chunker một collection (`grounded_rag_structural`, `grounded_rag_recursive`),
  vì chunk của hai chiến lược không được lẫn vào nhau.

## Đo lường

`hybrid: true` so với `false` trên cùng cấu hình, chỉ số `retrieval_recall`.
