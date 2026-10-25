# 12 — Thuật ngữ

## AI / truy xuất thông tin

| Thuật ngữ | Nghĩa trong dự án | Ở đâu |
|---|---|---|
| **RAG** (Retrieval-Augmented Generation) | Truy xuất đoạn tài liệu liên quan rồi đưa cho LLM để sinh câu trả lời dựa trên chúng | toàn dự án |
| **Hallucination** (bịa) | Câu trả lời khẳng định điều mà tài liệu được trích không nói | `eval/metrics.py::hallucinated` |
| **Grounded / có căn cứ** | Mệnh đề suy ra được từ đoạn nó trích dẫn. Khác với *đúng*: một câu có thể có căn cứ mà vẫn trả lời sai câu hỏi | guard |
| **Chunk** | Một đoạn văn bản được index; ở đây thường là một Khoản kèm tiêu đề Điều | `types.Chunk` |
| **Chunker** | Cách cắt văn bản thành chunk: `recursive` (theo kích thước) hoặc `structural` (theo Điều/Khoản) | `ingest/chunkers.py` |
| **Embedding / dense vector** | Vector số biểu diễn nghĩa của văn bản (bge-m3, 1024 chiều); tìm bằng cosine | `retrieval/embedder.py` |
| **Sparse vector** | Vector thưa theo từ vựng; ở đây là trọng số BM25 của từng token | `retrieval/lexical.py` |
| **BM25** | Hàm xếp hạng từ vựng cổ điển: tần suất từ có bão hòa (`k1`), chuẩn hóa độ dài (`b`), nhân IDF | `retrieval/lexical.py` |
| **IDF** | Inverse document frequency — từ càng hiếm trong corpus càng có trọng số cao | Qdrant `Modifier.IDF` |
| **Hybrid search** | Kết hợp dense và sparse | `corrective.search` |
| **RRF** (Reciprocal Rank Fusion) | Gộp nhiều danh sách xếp hạng bằng tổng `1/(k + rank)`, chỉ dùng thứ hạng | `retrieval/hybrid.py` |
| **Reranker / cross-encoder** | Model đọc **cặp** (câu hỏi, đoạn) cùng lúc để chấm mức liên quan; chính xác hơn embedding nhưng chậm | `retrieval/reranker.py` |
| **Bi-encoder** | Model mã hóa câu hỏi và đoạn **riêng rẽ** (embedding) — nhanh, dùng cho bước tìm đầu | bge-m3 |
| **Top-k** | Số kết quả giữ lại ở mỗi bước | `RetrievalConfig` |
| **Retrieval floor** (`min_score`) | Ngưỡng điểm rerank; không đoạn nào vượt thì không gọi LLM | `corrective.merge` |
| **Retrieval recall** | Tỉ lệ đoạn gold lọt vào ngữ cảnh đưa cho LLM | `eval/metrics.py` |
| **Recall@k, MRR** | Recall trong k kết quả đầu; trung bình nghịch đảo thứ hạng của kết quả đúng đầu tiên. **Chưa có** trong dự án | kế hoạch S1 |
| **Citation precision / recall** | Trong các đoạn được trích, bao nhiêu là gold / trong gold, bao nhiêu được trích | `eval/metrics.py` |
| **CRAG** (Corrective RAG) | Đánh giá chất lượng truy xuất; yếu thì viết lại truy vấn và tìm lại | `retrieval/corrective.py` |
| **Agentic RAG** | RAG có bước lập kế hoạch/tự sửa do LLM điều khiển; ở đây chỉ là một vòng có trần | cấu hình `agentic` |
| **Planner** | Lời gọi LLM trả JSON `{in_domain, queries}` để viết lại/tách câu hỏi | `prompts._PLANNER_PROMPT` |
| **HyDE** | Sinh một câu trả lời giả để làm truy vấn — **cố tình không dùng** | ADR-0005 |
| **NLI** (Natural Language Inference) | Bài toán phân loại quan hệ giữa *premise* và *hypothesis*: entailment / neutral / contradiction | `guard/nli_verifier.py` |
| **Premise / hypothesis** | Premise = đoạn tài liệu được trích; hypothesis = mệnh đề trong câu trả lời | guard |
| **Entailment** | Premise kéo theo hypothesis. Guard dùng `P(entailment)` làm điểm | guard |
| **Premise view** | Một phần của khoản luật (một mục, một câu) kèm tiêu đề và câu dẫn, chấm riêng rồi lấy max | `premise_views` |
| **Claim / mệnh đề** | Một câu khẳng định trong câu trả lời, kèm mã trích dẫn | `types.Claim` |
| **Verdict** | Kết luận cho một mệnh đề: `supported` / `unsupported` / `uncited` / `null` | `types.Verdict` |
| **τ (tau)** | Ngưỡng entailment để coi là `supported`; guard dùng 0.50 | `guard.entailment_threshold` |
| **Guard** | Lớp kiểm chứng mệnh đề + chính sách bỏ/sinh lại/từ chối | `guard/` |
| **Abstention / từ chối** | Hệ thống không trả lời (`abstained` hoặc `no_context`) | `types.AnswerStatus` |
| **Correct / false abstention** | Từ chối câu không có đáp án (tốt) / từ chối câu có đáp án (chi phí của guard) | `eval/metrics.py` |
| **Regeneration / sinh lại** | Gọi LLM lần nữa kèm danh sách mệnh đề không đạt | `policy.regeneration_feedback` |
| **LLM-as-judge** | Dùng một LLM để chấm câu trả lời của LLM khác | RAGAS |
| **RAGAS** | Bộ metric đánh giá RAG bằng LLM judge: faithfulness, answer relevancy, context precision, context recall | `eval/ragas_eval.py` |
| **Closed-book** | Hỏi model mà không đưa tài liệu, để xem RAG có mua được gì | `eval/closed_book.py` |
| **Ablation** | Tắt/đổi một thành phần để đo đóng góp của nó | bốn cấu hình |
| **Dev / test split** | Dev: dữ liệu để hiệu chỉnh (τ); test: dữ liệu để báo cáo, chưa từng dùng để chỉnh | dataset |
| **Thước đo (instrument)** | Cách eval quyết định một mệnh đề có căn cứ hay không — giống nhau cho mọi cấu hình | `eval/instrument.py` |
| **Đo vòng tròn** | Dùng chính model của guard để đo guard — kết quả không độc lập | README, [08](08-evaluation.md) |
| **Bootstrap CI** | Khoảng tin cậy ước lượng bằng lấy mẫu lại có hoàn lại. **Chưa có** | kế hoạch S1 |
| **Thinking model** | Model tiêu token cho suy nghĩ ẩn trước khi trả lời → dễ bị cắt ở `max_tokens` | `truncated` |
| **Mock provider** | Chế độ chạy toàn pipeline bằng thành phần giả, không key, không model | `LLM_PROVIDER=mock` |
| **Provider** | Dịch vụ LLM: Gemini, Ollama, vLLM, OpenAI, Anthropic | `llm_client.py` |
| **OpenAI-compatible** | API theo giao thức `/chat/completions` của OpenAI; vLLM, Ollama, Gemini đều hỗ trợ | `OpenAICompatClient` |
| **AWQ** | Lượng tử hóa trọng số 4-bit; dùng cho Qwen2.5-7B trên vLLM | compose |
| **SSE** (Server-Sent Events) | Server đẩy sự kiện một chiều qua HTTP | `/chat/stream` |

## Kỹ thuật backend

| Thuật ngữ | Nghĩa | Ở đâu |
|---|---|---|
| **Event loop** | Vòng lặp của asyncio chạy mọi coroutine trên một luồng; bị chặn thì mọi request chờ | FastAPI |
| **Oldest-first pool** | Pool luồng xếp lời gọi model theo thời điểm request đến | `compute.py` |
| **Idempotent ingest** | Ingest lại cùng dữ liệu không tạo bản sao (id theo hash nội dung) | `chunkers._chunk_id`, `store._point_id` |
| **Named vectors** | Qdrant cho một point nhiều vector có tên (`dense`, `sparse`) | `QdrantStore` |
| **Payload filter** | Lọc theo metadata trong Qdrant trước khi xếp hạng (ngày hiệu lực) | `_in_force_filter` |
| **Constant-time compare** | So sánh chuỗi không lộ thông tin qua thời gian (`hmac.compare_digest`) | `require_admin` |
| **Path traversal** | Dùng `..`/symlink để đọc ngoài thư mục cho phép; chặn bằng `resolve()` + `is_relative_to` | `corpus_dir` |
| **Backoff / Retry-After** | Chờ tăng dần giữa các lần thử lại; tôn trọng thời gian server yêu cầu | `_retry_wait` |
| **Contextvar** | Biến theo ngữ cảnh request trong asyncio, copy được sang luồng | `tracing._steps`, `compute._arrival` |

## Pháp luật

| Thuật ngữ | Nghĩa |
|---|---|
| **Bộ luật / Luật** | Văn bản do Quốc hội ban hành; corpus có Bộ luật Lao động 2019 và Luật BHXH 2024 |
| **Chương / Mục** | Cấp nhóm lớn trong văn bản; trong dự án là metadata `chapter`, không phải nội dung chunk |
| **Điều** | Đơn vị cơ bản ("Điều 35. Quyền đơn phương chấm dứt…"); `Chunk.article` |
| **Khoản** | Đánh số "1.", "2." trong một Điều; mỗi khoản là một chunk structural; `Chunk.clause` |
| **Điểm** | Đánh chữ "a)", "b)" trong một Khoản; guard chấm từng điểm như một premise view |
| **Số hiệu** | Mã văn bản: 45/2019/QH14 |
| **Công báo** | Ấn phẩm chính thức đăng văn bản pháp luật; nguồn của corpus |
| **Hiệu lực** (`effective_date`, `expiry_date`) | Khoảng thời gian văn bản được áp dụng; `as_of` lọc theo đó |
| **Hợp nhất** | Gộp văn bản gốc với các lần sửa đổi; corpus **chưa** hợp nhất |
| **Nghị định, thông tư** | Văn bản hướng dẫn thi hành luật của Chính phủ, bộ; **chưa có** trong corpus |
| **`ref`** | Địa chỉ dạng `bo_luat_lao_dong_2019:Điều 35:1` = văn bản : Điều : số Khoản |

## Bốn loại câu hỏi của dataset

| Loại | Ví dụ ý tưởng |
|---|---|
| `answerable` | "Nghỉ việc phải báo trước bao nhiêu ngày?" → Điều 35 khoản 1 |
| `unanswerable_out_of_scope` | Câu thuộc luật khác (thuế, đất đai…) |
| `unanswerable_false_premise` | "Hợp đồng lao động phải công chứng trong bao nhiêu ngày?" — giả định một quy định không tồn tại |
| `unanswerable_near_miss` | Đúng chủ đề, đúng thuật ngữ, nhưng chi tiết được hỏi không có trong văn bản |

---

[← 11 — Kiểm thử](11-testing.md) · [Handbook](README.md) · [13 — Giới hạn & lệch tài liệu →](13-known-gaps.md)
