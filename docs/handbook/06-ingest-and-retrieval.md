# 06 — Ingest & retrieval

## 1. Corpus

| File | Văn bản | Dòng | Chunk structural |
|---|---|---|---|
| `data/corpus/bo_luat_lao_dong_2019.md` | Bộ luật Lao động 2019, 45/2019/QH14, hiệu lực 01/01/2021 | 1.292 | 684 |
| `data/corpus/luat_bao_hiem_xa_hoi_2024.md` | Luật BHXH 2024, 41/2024/QH15, hiệu lực 01/07/2025 | 1.114 | 557 |
| `data/sample_corpus/bo_luat_lao_dong_2019.md` | Trích Điều 35, khoản 1 Điều 105, khoản 1 Điều 113 | 36 | — |

Cả hai thư mục **được commit** (~500 KB): clone về là có corpus, CI giải được mọi
gold ref mà không phụ thuộc trang Công báo còn sống.

### Tạo lại corpus — `scripts/prepare_corpus.py` (`make corpus`)

1. Tải PDF Công báo vào `.cache/corpus_raw/`.
2. Đọc lớp text bằng pymupdf; bỏ header "CÔNG BÁO/Số …" và số trang (thường nằm
   giữa một khoản); nối các dòng bị ngắt cứng.
3. **Kiểm tra** trước khi ghi: đủ mọi Điều, khoản đánh số liên tục 1..n.
4. Ghi `data/corpus/*.md` kèm front matter.

### Front matter

```yaml
---
title: Bộ luật Lao động 2019
number: 45/2019/QH14
issued_by: Quốc hội
effective_date: 2021-01-01
source: Công báo số 993 + 994, ngày 26-12-2019
# expiry_date: để trống = còn hiệu lực
---
```

Với PDF, metadata nằm ở file `<tên>.meta.yaml` đặt cạnh. Trường lạ (`source`)
bị bỏ qua khi validate thành `DocMeta`.

### Giới hạn của corpus

- Bản gốc khi ban hành; các lần sửa đổi sau đó **chưa được hợp nhất**.
- Không có nghị định, thông tư hướng dẫn.
- Điều 219 Bộ luật Lao động trích nguyên văn khoản của luật khác, nên số khoản
  trong điều này không liên tục và `ref` của chunk trong đó không đáng tin.

## 2. Loader — `ingest/loaders.py`

```python
iter_corpus(root)   # rglob, sắp xếp, chỉ .md .txt .pdf
load_file(path)     # → Document(doc_id=path.stem, text, meta: DocMeta)
split_front_matter  # "---\n<yaml>\n---\n<body>" → (body, dict); không có thì trả nguyên
```

`doc_id` = tên file không đuôi (`bo_luat_lao_dong_2019`). Đây cũng là tiền tố của
`chunk_id` và `ref`.

## 3. Chunker — `ingest/chunkers.py`

### `structural` (dùng ở `full`, `agentic`)

Đọc **từng dòng** với bốn regex:

| Regex | Khớp | Hành động |
|---|---|---|
| `CHAPTER_RE` `^\s*(Chương\|CHƯƠNG)\s+([IVXLCDM]+\|\d+)\b` | "Chương III" | đóng Điều hiện tại, ghi nhớ `chapter` |
| `SECTION_RE` `^\s*(Mục\|MỤC)\s+\d+\b` | "Mục 1" | đóng Điều hiện tại |
| `ARTICLE_RE` `^\s*(Điều\s+\d+[a-z]?)\s*[.:]\s*(.*)$` | "Điều 35. Quyền …" | mở Điều mới. **Dấu `.` hoặc `:` bắt buộc**, để dòng bị ngắt "Điều 35 của Bộ luật này…" không bị tưởng là Điều mới |
| `CLAUSE_RE` `^\s*(\d+)\.\s+` | "1. Người lao động …" | ranh giới Khoản trong thân Điều |

Mỗi Khoản thành một chunk, **dòng đầu là tiêu đề Điều**:

```
Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động của người lao động
1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động nhưng phải báo trước ...
```

Vì sao mang tiêu đề: khoản 2 Điều 35 tự nó chỉ nói "không cần báo trước trong
trường hợp…"; có tiêu đề thì retriever lẫn premise NLI đều biết nó nói về gì.

- Điều không chia khoản → một chunk cho cả Điều (`clause = None`).
- Khoản dài hơn ngân sách (1800 ký tự trừ tiêu đề) → cắt theo dòng (`_pieces`);
  nếu là danh sách có câu dẫn kết thúc bằng ":", **mỗi mảnh lặp lại câu dẫn**
  để mục d) không mất chủ thể.
- Không tìm thấy Điều nào → lùi về `recursive_chunk` (không bao giờ trả rỗng).

### `recursive` (dùng ở `baseline`, `threshold`)

Cắt đệ quy theo `["\n\n", "\n", ". ", " "]` với ngân sách 1200 ký tự, overlap
150 ký tự bắt đầu từ ranh giới từ. Corpus hiện tại cho 347 chunk recursive (so
với 1.241 chunk structural). Không có `article`/`clause`, nên `ref` =
`chunk_id`. Một lỗi đã sửa: ghép overlap thẳng vào mảnh sau từng tạo ra
"lao động1." — giờ có `\n` ở giữa.

### `chunk_id` và `ref`

```python
chunk_id = f"{doc_id}:{sha256(f'{doc_id}::{text}')[:16]}"   # hash nội dung
ref      = "bo_luat_lao_dong_2019:Điều 35:1"                # Chunk.ref (computed)
```

- `chunk_id` theo nội dung → ingest lại cùng văn bản **không nhân đôi**.
- `ref` là địa chỉ người đọc hiểu được, cũng là định dạng `gold_chunks` của
  dataset. Chunk không có cấu trúc thì `ref = chunk_id`.

## 4. Lưu trữ — `retrieval/store.py`

### Một collection mỗi chunker

`get_store("structural")` → `QdrantStore("grounded_rag_structural")`;
`get_store("recursive")` → `grounded_rag_recursive`. Hai chiến lược là hai chỉ
mục khác nhau của cùng corpus; dùng chung thì `baseline` sẽ truy xuất chunk của
`full` và so sánh mất nghĩa. `make ingest` vì vậy chạy hai lần (một cho mỗi
chunker).

### Schema một point

```
id      : uuid5(NAMESPACE_URL, chunk_id)            # ổn định qua các lần ingest
vectors : "dense"  → 1024 float, cosine (bge-m3, đã chuẩn hóa L2)
          "sparse" → {crc32(token): trọng số TF bão hòa của BM25}, Modifier.IDF
payload : Chunk.model_dump() + ref + ingested_at    # gồm cả text
```

Payload chứa `text` nên dựng prompt không cần quay lại file gốc. Index HNSW mặc
định (vài nghìn chunk, không cần tune).

### `upsert`

1. Bỏ trùng theo `chunk_id` trong batch.
2. `retrieve` theo lô 256 id để biết point nào **đã có**.
3. Chỉ embed chunk **mới** (lô 64) → ingest lại corpus không đổi gần như miễn phí.
4. `avg_len` của BM25 tính trên **toàn batch**, không chỉ phần mới.
5. Trả số chunk đã ghi mới (`written`).

**Hệ quả (lỗi B6, còn tồn):** upsert chỉ thêm. Sửa một khoản thì chunk cũ (hash
cũ) vẫn nằm trong index cạnh chunk mới. Cách hiện tại: CLI `--recreate` (xóa
collection rồi ghi lại). Kế hoạch sửa bằng alias: S4 trong
[../13-sprint-plan.md](../13-sprint-plan.md).

### `InMemoryStore` (mock)

Cùng protocol `VectorStore`: cosine trên list Python + `BM25Index` thuần Python.
Sống trong một tiến trình, mất khi restart.

## 5. Tìm kiếm

### Dense

`embedder.encode([query])` → `query_points(using="dense", limit=20,
query_filter=_in_force_filter(as_of))`.

### Sparse — BM25 (`retrieval/lexical.py`)

**Tokenizer:** chuẩn hóa NFC, viết thường, tách `\w+`, số bỏ số 0 đầu
(`"08"` → `"8"`), rồi thêm bigram âm tiết liền kề:

```
"Hợp đồng lao động 08 giờ" → [hợp, đồng, lao, động, 8, giờ,
                              hợp_đồng, đồng_lao, lao_động, động_8, 8_giờ]
```

Bigram xấp xỉ tách từ tiếng Việt mà không cần thư viện tách từ.

**Công thức** (`K1 = 1.2`, `B = 0.75`):

```
tf_weight(tf, dl, avgdl) = tf·(K1+1) / (tf + K1·(1 − B + B·dl/avgdl))
idf(N, df)               = ln((N − df + 0.5)/(df + 0.5) + 1)
```

Trong Qdrant: phía tài liệu lưu `tf_weight` cho mỗi token (chỉ số = `crc32`,
ổn định giữa các tiến trình, khác `hash()`); phía truy vấn mỗi token trọng số
1.0; Qdrant nhân IDF lúc truy vấn (`Modifier.IDF`). Vì sao BM25 thay vì sparse
của bge-m3: [ADR-0006](../adr/0006-bm25-sparse-retrieval.md).

### Lọc hiệu lực (`as_of`)

```
(effective_date trống HOẶC effective_date ≤ as_of)
VÀ (expiry_date trống HOẶC expiry_date > as_of)
```

Chạy **trong Qdrant**, trước khi xếp hạng (`_in_force_filter`). Ngày trống không
bao giờ loại chunk. `as_of` mặc định là hôm nay. Với pháp luật, điều khoản hết
hiệu lực là câu trả lời **sai**, không phải câu trả lời cũ.

Giới hạn (B7): ngày hiệu lực lấy từ **văn bản**, áp chung cho mọi khoản; chưa mô
hình được một khoản bị sửa đổi từ ngày khác.

### Hợp nhất — RRF (`retrieval/hybrid.py`)

```
score(chunk) = Σ_runs 1 / (60 + rank + 1)
```

Chỉ dùng thứ hạng, bỏ qua điểm gốc (cosine và BM25 không cùng thang). Cắt còn
`rerank_candidates` (20).

### Rerank — `retrieval/reranker.py`

`BGEReranker`: cross-encoder đọc cặp (query, chunk), batch 16, `max_length 512`,
`truncation="only_second"` (cắt chunk, không cắt câu hỏi), điểm =
`sigmoid(logit)` ∈ [0, 1], giữ `rerank_to` (5).

Sigmoid được **tự tính** thay vì để mặc định thư viện, vì `min_score` trong YAML
là ngưỡng trên đúng thang này. `LexicalReranker` (mock) cho điểm = tỉ lệ token
câu hỏi có trong đoạn, cũng thang 0–1, nên floor hoạt động đúng nghĩa trong mock.

Đây là bước **chậm nhất** trên CPU: 5–12 giây/câu cho 20 ứng viên.

### Floor

Điểm rerank `< min_score` bị loại trong `merge`. Không còn gì → `no_context`,
**không gọi LLM**. Trên lượt chạy 2026-10-12, floor 0.30 chặn 17/30 câu không có
đáp án, đổi lại 2 câu trả lời được bị chặn nhầm (false abstention 1 → 3 trên 50).

Đo đánh đổi của floor mà không cần LLM: `python scripts/sweep_floor.py --out
reports/floor-sweep.json` — với mỗi ngưỡng: bao nhiêu câu trả lời được vượt
floor (`reach_llm`), bao nhiêu câu còn giữ được khoản gold (`gold_survives`), bao
nhiêu câu không có đáp án bị chặn miễn phí (`floor_blocks`).

## 6. Truy xuất sửa lỗi (`agentic`) — `retrieval/corrective.py`

Kiểu CRAG, tự viết, có trần cứng. Giải hai lỗi của floor:

1. Câu nói kiểu đời thường ("nghỉ việc" thay vì "đơn phương chấm dứt hợp đồng
   lao động") → điểm rerank thấp → bị floor chặn nhầm.
2. Câu nhiều ý ("báo trước bao lâu **và** được nghỉ phép mấy ngày") → không đoạn
   nào khớp đủ mạnh cả hai ý.

Cấu hình (`configs/agentic.yaml`):

| Tham số | Giá trị | Nghĩa |
|---|---|---|
| `confident_score` | 0.60 | Điểm cao nhất ≥ ngưỡng này thì không cần vòng sửa |
| `max_rounds` | 1 | Số vòng tối đa (validate 0–3) |
| `max_queries` | 3 | Số truy vấn planner được đề xuất (1–5) |
| `max_llm_calls` | 4 | Trần lời gọi cho cả câu hỏi |

Planner prompt (`prompts._PLANNER_PROMPT`) có bốn quy tắc; quy tắc 3 quan trọng
nhất: **không thêm con số, điều khoản hay chi tiết mà câu hỏi không nhắc tới** —
truy vấn viết lại mà bịa chi tiết sẽ kéo truy xuất về phía chi tiết đó, tức là
cài sẵn một lần bịa trước khi sinh. Planner cũng nhận danh sách truy vấn đã thử
để không lặp lại; truy vấn chỉ khác câu gốc ở dấu câu bị bỏ qua (`_key`).

Kết quả đo (2026-10-12): 24 lời gọi planner, 21 rơi vào câu không có đáp án; tăng
retrieval recall của câu `colloquial` từ 0.89 lên 1.00 nhưng **không cứu được câu
nào** (câu duy nhất vượt floor, `a004`, sau đó bị guard từ chối). Net: +0.4 lời
gọi LLM/câu cho cùng tỉ lệ từ chối. Vì sao không dùng LangGraph:
[ADR-0005](../adr/0005-corrective-retrieval-loop.md).

## 7. Tham số retrieval theo cấu hình

| | `baseline` | `threshold` | `full` | `agentic` |
|---|---|---|---|---|
| `chunker` | recursive | recursive | structural | structural |
| `hybrid` | true | true | true | true |
| `top_k_dense` / `top_k_sparse` | 20 / 20 | 20 / 20 | 20 / 20 | 20 / 20 |
| `rerank_candidates` → `rerank_to` | 20 → 5 | 20 → 5 | 20 → 5 | 20 → 5 |
| `min_score` (floor) | **0.0** (tắt) | 0.30 | 0.30 | 0.30 |
| corrective | tắt | tắt | tắt | **bật** |

Hybrid + rerank giống nhau ở mọi cấu hình, nên bảng kết quả cô lập được tác dụng
của floor, guard, chunker và vòng sửa lỗi.

## 8. Lệnh thường dùng

```bash
make up-qdrant                                    # Qdrant :6333
make ingest                                       # cả hai chunker vào data/corpus
python -m grounded_rag.ingest.pipeline --source data/corpus \
    --config configs/full.yaml --recreate         # dựng lại index structural
curl localhost:6333/collections                   # xem collection đã có
```

Đo trên i7-11800H: ingest 1.241 chunk structural bằng bge-m3 mất 4 phút 20 giây,
cần ~3,6 GB RAM.

---

[← 05 — Pipeline truy vấn](05-query-pipeline.md) · [Handbook](README.md) · [07 — Guard →](07-guard.md)
