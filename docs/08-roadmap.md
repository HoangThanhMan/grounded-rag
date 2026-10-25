# 08 — Lộ trình 3 tuần

~3h/ngày, một người. Mốc cuối mỗi tuần là thứ phải chạy được, không phải thứ
"gần xong".

## Trạng thái — 2026-09-19

Code của tuần 1 và phần lớn tuần 3 đã được viết trong đợt đối chiếu với tài
liệu tham khảo. **Cột "Xong khi" vẫn phải
được kiểm chứng bằng model thật và corpus thật.** Chạy được với mock không có
nghĩa là ngày đó đã xong.

| Hạng mục | Code | Đã kiểm chứng tới đâu |
|---|---|---|
| Corpus thật, loader + front matter, chunker có tiêu đề Điều | ✅ | `make corpus` từ Công báo: Bộ luật LĐ 2019 (220 Điều, 684 chunk) + Luật BHXH 2024 (141 Điều, 557 chunk); đã xem mẫu chunk |
| Embedder bge-m3, Qdrant dense + BM25, lọc hiệu lực | ✅ | bge-m3 thật ingest 1.241 + 347 chunk vào server Qdrant v1.19.1 |
| Reranker cross-encoder | ✅ | bge-reranker-v2-m3 thật chạy, nhưng 5–12 giây/câu trên CPU |
| Provider Gemini / Ollama / vLLM / OpenAI / Anthropic | ✅ | Gemini thật (`gemini-3.1-flash-lite`). Các provider khác: unit test với transport giả |
| NLI verifier (cắt premise dài, định dạng output) | ✅ | Chạy với mDeBERTa-v3 thật — xem bên dưới |
| Vòng truy xuất sửa lỗi (`agentic`) | ✅ | Chạy thật trên 7 câu — xem bên dưới |
| Eval: một công cụ đo, gold theo nội dung, RAGAS | ✅ | Eval thật trên 80 câu. RAGAS với giám khảo thật: chưa |
| `meta.steps`, `/metrics` | ✅ | Unit test |
| Langfuse | ✅ | Export một trace/câu trả lời: span mỗi bước, generation mỗi lời gọi LLM, verdict của guard thành score. Unit test với client giả — **chưa xem trace trên UI thật** |
| Tập 100 câu có nhãn | ✅ | 63 answerable + 37 unanswerable sau kiểm tra chéo lần hai (đổi nhãn 3 câu, xem LABELING.md); tách 20 câu `dev` để hiệu chỉnh τ, chấm trên 80 câu `test`. `make check-dataset` giải được mọi gold ref. **Chưa chấm tay 30 câu** |
| Giao diện web | ✅ | `app/web/`, do API phục vụ ở `/`; mệnh đề tô màu theo verdict, thước entailment có vạch τ |
| Hiệu chỉnh τ | ✅ | `make calibrate` trên 20 câu dev, đường cong ở `docs/img/tau-curve.svg`, τ = 0.50. Kết luận quan trọng hơn con số: trên dev **không có τ nào tách được mệnh đề đúng khỏi mệnh đề sai** ([06](06-guard-design.md)) |
| Bảng số thật trong README | ✅ | Chạy 2026-10-12 (WS0): `gemini-3.1-flash-lite`, 4 cấu hình × 80 câu `test`, ~4 giờ trên CPU. Report ở `reports/2026-10-12-gemini/`. Retrieval floor là lợi ích rẻ nhất; vòng corrective tốn thêm 0.4 lời gọi/câu mà không cứu được câu nào. Số 0 hallucination của guard là đo vòng tròn — cần chấm tay |
| Prompt sinh | ✅ | Sửa lỗi model thay con số bằng mã trích dẫn ([09](09-runbook.md)); 4/4 lượt giữ đúng con số sau khi sửa |

### Lượt chạy thật đầu tiên — 7 câu, 2026-09-11

Toàn bộ stack thật: bge-m3, bge-reranker-v2-m3, mDeBERTa, Qdrant, Gemini
`gemini-3.1-flash-lite`; mỗi cấu hình một tiến trình (`python -m eval.run`).
7 câu = 6 câu mẫu + 1 câu về Luật BHXH. **Không phải benchmark** — quá ít câu
để kết luận điều gì. Report: `reports/smoke-2026-09-11/`.

| Configuration | Halluc. | Correct abst. | False abst. | Cite prec. | Retr. recall | LLM calls/q | p95 (ms) |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 1.00 | 0.00 | 0.83 | 1.00 | 1.00 | 16 671 |
| agentic | 0.00 | 1.00 | 0.00 | 0.83 | 1.00 | 1.57 | 22 533 |
| threshold | 0.43 | 1.00 | 0.00 | 0.54 | 0.88 | 0.71 | 13 957 |
| baseline | 0.29 | 1.00 | 0.00 | 0.79 | 1.00 | 1.00 | 13 584 |

Bốn điều cần biết khi đọc bảng — mỗi điều là việc cho các ngày tới:

1. **Halluc. của baseline/threshold phần lớn là NLI chấm sai, không phải bịa.**
   Đọc tay, các mệnh đề bị chấm "không căn cứ" đều đúng theo luật. Ví dụ: một
   câu gộp khoản 1 và 2 Điều 105 được 0.09 dù premise chứa đủ cả hai khoản;
   câu "từ đủ 70 đến dưới 75 tuổi thuộc hộ nghèo" được 0.24. mDeBERTa yếu với
   câu diễn đạt lại một khoản dài có điều kiện. Chấm tay 30 câu là bắt buộc, và
   ngày 9 / ngày 14 quan trọng hơn dự kiến.
2. **Guard của `full` chặn nhầm câu đúng:** "theo tuần thì không quá 10
   giờ/ngày" (Điều 105:2) được 0.30 và bị bỏ, câu trả lời thành `partial`. Cùng
   điểm yếu NLI ở mục 1, nhưng lần này người dùng mất một câu đúng. (Câu "70–75
   tuổi" bị guard bỏ ở `full` thì đúng: model trích khoản 1 cho nội dung của
   khoản 2.)
3. **`agentic` chưa mua được gì trên 7 câu này.** Câu hai ý a003 có đủ bằng
   chứng ngay lần tìm đầu nên không cần planner. Còn hai câu ngoài phạm vi thì
   được planner viết lại, vượt floor, tới LLM rồi model tự từ chối: thêm 1 lời
   gọi và ~15 giây mỗi câu. Đúng rủi ro ADR-0005 đã dự đoán.
4. **Độ trễ:** retrieve 5–12 giây/câu, gần như toàn bộ là cross-encoder trên
   CPU; p95 17 giây, xa yêu cầu N1 < 6 giây. Cần đo `rerank_candidates` 20 → 8,
   hoặc thử reranker nhỏ hơn.

Lượt chạy này cũng làm lộ các lỗi đã được sửa: câu trả lời bị cắt vì model
"thinking" tiêu hết `max_tokens` (nay có `truncated_generations`); chunk
recursive dính chữ ở mép overlap ("lao động1."); thước đo chấm trên premise
dài quá 512 token; so khớp gold theo trùng lặp thay vì chứa. Và một vấn đề
nhãn: u002 "mức phạt đi làm muộn" thật ra có đáp án bác tiền đề ở Điều 127:2
(xem LABELING.md).

### Tín hiệu sớm cho rủi ro ngày 9

`python scripts/nli_probe.py` — 11 cặp với
`mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, τ = 0.60. **Chưa phải bài kiểm
tra 20 cặp của ngày 9**, mới là dấu hiệu đầu tiên:

| Cặp | P(entail) | Guard |
|---|---|---|
| 3 mệnh đề đúng (kể cả diễn đạt lại, "08 giờ" → "8 giờ") | 0.82 – 0.96 | cho qua ✓ |
| Đổi số: 45 → 90 ngày, 45 → 30 ngày, 8 → 10 giờ/ngày | 0.13 – 0.42 | chặn ✓ |
| Phủ định ("không phải báo trước") | 0.01 | chặn ✓ |
| Đổi điều kiện (hợp đồng *xác định* thời hạn) | 0.23 | chặn ✓ |
| **Đổi chủ thể** (người *sử dụng* lao động phải báo trước 45 ngày) | **0.84** | **cho qua ✗** |
| **Near-miss** (người lao động *thử việc* phải báo trước 45 ngày) | **0.73** | **cho qua ✗** |
| **Đổi số** 48 → 40 giờ/tuần | **0.72** | **cho qua ✗** |

Model mạnh với phủ định và phần lớn các thay đổi số, nhưng yếu với đổi chủ thể
và thêm điều kiện — kiểu "trùng từ vựng cao nhưng sai nghĩa". Đó chính là lỗi
của câu `near_miss`, loại khó nhất trong tập đánh giá.

**Đã xử lý (2026-09-17).** Probe mở rộng lên 24 cặp, thử cả
`xlm-roberta-large-xnli`, kết quả và bảng lỗi theo nhóm nằm ở
[06](06-guard-design.md#probe-nli-trên-24-cặp-2026-09-17). Tóm tắt: chấm theo từng
mục của khoản sửa hết lỗi chặn nhầm câu đúng, luật con số sửa hết lỗi đổi số —
đúng phương án dự phòng số 3 ở đây, nhưng bằng một quy tắc rẻ thay vì fine-tune.
Đổi chủ thể và near-miss thì **không lớp nào chạm tới được**, và model lớn gấp
đôi còn tệ hơn ở đúng nhóm đó, nên giữ mDeBERTa. Fine-tune ViNLI vẫn là việc
chưa làm ([ADR-0007](adr/0007-no-generator-fine-tuning.md)).

## Tuần 1 — RAG chạy được đầu-cuối

| Ngày | Việc | Xong khi |
|---|---|---|
| 1 | Tải corpus, `loaders.py` | `python -m grounded_rag.ingest.pipeline` đọc được file |
| 2 | Hoàn thiện `chunkers.py`, kiểm tra bằng mắt 20 chunk | `test_chunkers.py` xanh |
| 3 | `embedder.py` + `store.py` với Qdrant thật | Ingest xong, search trả về đúng chunk |
| 4 | `reranker.py`, ngưỡng retrieval | Câu hỏi vớ vẩn trả `no_context` |
| 5 | `llm_client.py` cho Gemini hoặc Ollama, `POST /chat` | Trả lời được kèm `[C1]` |
| 6 | SSE + Streamlit thô | Nhìn thấy câu trả lời trên trình duyệt |
| 7 | `docker compose up` chạy trọn vẹn | Clone máy khác vẫn chạy |

**Mốc:** hỏi được, trả lời được, có nguồn.

## Tuần 2 — Guard + tập đánh giá

| Ngày | Việc | Xong khi |
|---|---|---|
| 8 | Hoàn thiện `claim_splitter.py` cho tiếng Việt | Test "Điều 35." xanh |
| 9 | `NLIVerifier` thật, **kiểm tra 20 cặp thủ công** | Biết NLI có dùng được cho tiếng Việt không |
| 10 | Cache + batch cho NLI | Verify 5 mệnh đề < 2s trên CPU |
| 11 | `policy.py`: sinh lại, bỏ mệnh đề, từ chối | `test_policy.py` xanh |
| 12–13 | **Xây tập 100 câu có nhãn** | `questions.jsonl` đủ 100 dòng |
| 14 | Hiệu chỉnh τ trên tập dev, vẽ đường P–R | Có hình đưa vào README |

**Mốc:** guard chặn được câu bịa trên ví dụ thủ công.

> Ngày 9 là điểm rủi ro lớn nhất. Nếu NLI đa ngữ quá yếu với tiếng Việt, phải
> biết ngay ngày 9 chứ không phải ngày 16. Phương án dự phòng: đổi sang
> `xlm-roberta-large-xnli`, hoặc fine-tune nhẹ trên ViNLI.

> Ngày 12–13 hay bị lùi và đó là sai lầm chết người — không có tập đánh giá thì
> không có số liệu, không có số liệu thì dự án chỉ là một demo nữa.

## Tuần 3 — Đo lường, vận hành, đóng gói

| Ngày | Việc | Xong khi |
|---|---|---|
| 15 | Hoàn thiện `eval/metrics.py`, `eval/run.py` | Chạy được một cấu hình ra JSON |
| 16 | Chạy bốn cấu hình, dựng bảng | Bảng có số thật |
| 17 | RAGAs + Langfuse tracing | Thấy trace trên Langfuse UI |
| 18 | GitHub Actions với `--gate` | Badge xanh |
| 19 | Streamlit tô màu verdict, quay demo 90 giây | Link YouTube |
| 20–21 | Viết `README.md` tiếng Anh | Người lạ hiểu dự án trong 2 phút |

**Mốc:** người lạ mở repo, hiểu dự án làm gì và tin vào số liệu.

## Định nghĩa "xong" — 2026-09-19

- [x] `git clone` → `docker compose up` → `make ingest` → chạy. Kiểm chứng
      đầu-cuối bằng stack thật: `answered`, mệnh đề `supported` 0.9949, trích
      đúng Điều 35:1
- [x] Quick start bằng `mock` thật sự trả lời được (`make seed`)
- [x] README có bảng so sánh bốn cấu hình với số thật (2026-10-12, Gemini)
- [x] README có ảnh demo hiện mệnh đề tô màu theo verdict
- [x] README có đường cong hiệu chỉnh τ
- [x] `eval/dataset/questions.jsonl` đủ 100 câu + `LABELING.md`
- [x] Mục "Limitations" trong README — nói rõ guard sai ở đâu
- [ ] Chấm tay 30 câu (script có; report đã có ở `reports/2026-10-12-gemini/`) ← **việc lớn nhất còn lại**
- [ ] RAGAS 10 câu bằng Gemini (report đã có)
- [ ] Video demo 90 giây, link trong README

Bốn mục dưới đây phụ thuộc vào một remote GitHub. Hoãn ngày 2026-09-19,
làm xong ngày 2026-10-12 (WS0 trong [11](11-spec-v2.md)):

- [x] `git remote` + push — <https://github.com/HoangThanhMan/grounded-rag>
- [x] CI badge trong README (CI chạy test trên Python 3.12 và 3.14, kèm bước `--gate`)
- [x] Repo có description
- [x] Topics: `rag`, `hallucination-detection`, `nli`, `qdrant`, `fastapi`,
      `vietnamese`, `legal-ai`, `llm-evaluation`

## Rủi ro

| Rủi ro | Dấu hiệu sớm | Xử lý |
|---|---|---|
| Gán nhãn tốn hơn dự kiến | Ngày 13 chưa đủ 60 câu | Rút xuống 70 câu, giữ tỉ lệ 60/40 |
| NLI yếu với tiếng Việt | Ngày 9, kiểm tra tay thấy sai nhiều | Đổi model hoặc fine-tune nhẹ trên ViNLI |
| CPU quá chậm | Verify một câu > 10s | Batch + cache; eval chạy qua đêm |
| Hết quota free tier | 429 từ provider | Chuyển `LLM_PROVIDER=ollama`, đã tách sẵn |
| Guard không cải thiện số liệu | Ngày 16 | Báo cáo trung thực + phân tích. **Không chỉnh số** |
| Planner (`agentic`) "sửa" câu `near_miss` thành câu trả lời được | `correct_abstention` của `near_miss` ở `agentic` thấp hơn `full` | Báo cáo; siết prompt planner hoặc để `agentic` tắt |

## Sau khi xong (chỉ khi đã tick hết mục trên)

- Router hai tầng: model rẻ trả lời trước, escalate khi guard báo thiếu căn cứ
- Corpus song ngữ, đo retrieval xuyên ngôn ngữ
- So sánh guard NLI với LLM-as-judge trên cùng benchmark → viết bài blog.
  Nguyên liệu đã có: `nli_vs_judge` trong `eval/ragas_eval.py`
- Đóng gói guard thành thư viện `pip install` độc lập
- Ablation retrieval: `hybrid: false`, sparse bge-m3 so với BM25 ([ADR-0006](adr/0006-bm25-sparse-retrieval.md))
- Bộ Hỏi–Đáp pháp luật trên Hugging Face làm nguồn câu hỏi ứng viên cho tập đánh giá lớn hơn
