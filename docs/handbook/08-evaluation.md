# 08 — Hệ thống đánh giá

Đây là phần có giá trị nhất của dự án: không có số đo thì guard chỉ là một demo.
Code nằm ở `eval/` (ngoài `src/`, dùng package như một thư viện) và `scripts/`.

## 1. Dataset — `eval/dataset/`

| File | Nội dung |
|---|---|
| `questions.jsonl` | 100 câu gán nhãn tay, dùng cho benchmark |
| `questions.sample.jsonl` | 6 câu trên `data/sample_corpus/`, cho CI |
| `LABELING.md` | Quy trình gán nhãn + CHANGELOG mọi lần sửa nhãn |

### Phân bố

| Loại | test | dev | Tổng | Kiểm tra điều gì |
|---|---|---|---|---|
| `answerable` | 50 | 13 | 63 | Trả lời đúng, trích dẫn đúng |
| `unanswerable_out_of_scope` | 12 | 3 | 15 | Câu hỏi thuộc luật khác → biết im lặng |
| `unanswerable_false_premise` | 10 | 3 | 13 | Giả định một quy định không tồn tại → không bịa theo |
| `unanswerable_near_miss` | 8 | 1 | 9 | **Bẫy khó nhất**: đúng chủ đề, đúng thuật ngữ, sai chi tiết |
| **Tổng** | **80** | **20** | **100** | |

Tags trên câu `answerable`: 11 `multi_part` (nhiều ý), 11 `colloquial` (cách nói
đời thường) — hai lát cắt vòng corrective sinh ra để xử lý.

**Tách dev/test:** 20 câu `"split": "dev"`, phân tầng theo loại, **chỉ** dùng
hiệu chỉnh τ. `eval.run` mặc định `--split test`. Báo cáo số trên dev là chấm
trên chính dữ liệu đã chọn ngưỡng.

### Định dạng một dòng

```json
{"id": "a001",
 "question": "Người lao động đơn phương chấm dứt hợp đồng lao động không xác định thời hạn phải báo trước bao nhiêu ngày?",
 "answerable": true, "gold_answer": "Ít nhất 45 ngày.",
 "gold_chunks": ["bo_luat_lao_dong_2019:Điều 35:1"],
 "type": "answerable", "split": "test", "tags": ["colloquial"]}
```

### Quy trình gán nhãn (tóm tắt `LABELING.md`)

1. LLM sinh 2 câu hỏi ứng viên mỗi chunk — **chỉ là nguyên liệu thô**.
2. Người duyệt từng câu; loại câu mơ hồ, câu nhiều chunk cùng trả lời được.
3. Ghi `gold_answer` (1–2 câu, lời của văn bản) và `gold_chunks` (theo `ref`).
4. Câu không trả lời được **viết tay**, kiểm tra bằng tìm toàn văn. Cẩn thận với
   `false_premise`: luật hay *bác* đúng tiền đề sai (ví dụ "mức phạt đi làm muộn"
   — Điều 127 khoản 2 cấm phạt tiền) → câu đó là `answerable`, đáp án là bác bỏ.
5. Kiểm tra chéo lần hai sau ít nhất một ngày (lần 2026-09-17 chuyển 3 câu
   `unanswerable` thành `answerable`).

Quy tắc: **không sửa tập đánh giá sau khi xem kết quả**; buộc phải sửa thì ghi
CHANGELOG và chạy lại cả bốn cấu hình.

### `scripts/check_dataset.py` (`make check-dataset`, chạy trong CI)

- Giải mọi gold ref qua đúng `ClauseIndex` mà metric dùng (ref hỏng sẽ âm thầm
  làm retrieval recall về 0).
- Kiểm tra mọi con số trong `gold_answer` có trong khoản gold.
- Tìm toàn văn câu `unanswerable` trong corpus; cảnh báo nếu corpus có thể trả
  lời (hiện còn một cảnh báo ở `u018`, đã ghi trong LABELING.md).

## 2. Thước đo — `eval/instrument.py`

**Một thước cho mọi cấu hình.** `hallucination_rate` được chấm **sau khi chạy**,
trên văn bản trả lời cuối, bằng cùng NLI verifier ở cùng ngưỡng
(`ENTAILMENT_THRESHOLD`, mặc định 0.50), bất kể cấu hình có guard hay không.
Bản đầu chấm baseline bằng một verifier luôn trả "supported" — bảng nghiêng về
guard mà không ai thấy.

`judge_claims(answer, verifier, threshold, index)`:

1. Câu từ chối (`abstained`, `no_context`) → không chấm.
2. `split_claims(answer.answer)`.
3. Mệnh đề không trích dẫn → `uncited`, 0.0.
4. Premise = với mỗi chunk được trích, `ClauseIndex.premises(chunk)`; ≥2 chunk
   thì thêm bản nối; ≥3 thì thêm từng cặp. Điểm = **max** trên mọi premise.

**`ClauseIndex`** dựng mọi khoản của corpus bằng `structural_chunk` **không giới
hạn kích thước** (khoản chỉ bị cắt để index, không bao giờ để đo).

**Premise cùng cỡ cho mọi cấu hình** (`premises`): chunk structural chấm đúng như
được trích; chunk recursive (không có cấu trúc) chấm với chính nó, **với từng
khoản nó chứa trọn**, và với từng cặp khoản liền kề. Lý do: cửa sổ recursive dài
565–680 token, vượt 512 token mDeBERTa đọc; lần chạy đầu, câu đúng được 0.02–0.32
khi chấm với cửa sổ và 0.85–0.97 khi chấm với khoản bên trong. Chấm thẳng thì
baseline "bịa" 57% — một con số đo kích thước chunk, không đo guard.

## 3. Metric — `eval/metrics.py`

| Metric | Định nghĩa | Tập câu |
|---|---|---|
| `hallucination_rate` | Tỉ lệ câu trả lời có ≥1 mệnh đề không `supported` theo thước đo (câu từ chối không tính là bịa) | tất cả |
| `correct_abstention` | Tỉ lệ câu không có đáp án mà hệ thống từ chối (`abstained` hoặc `no_context`) | unanswerable |
| `false_abstention` | Tỉ lệ câu có đáp án mà hệ thống từ chối | answerable |
| `citation_precision` | Trong các chunk được trích ở **câu trả lời cuối**, tỉ lệ khớp gold | answerable đã trả lời |
| `citation_recall` | Trong gold, tỉ lệ được trích | answerable đã trả lời |
| `retrieval_recall` | Trong gold, tỉ lệ lọt vào ngữ cảnh đưa cho LLM | answerable |
| `latency_p50_ms`, `latency_p95_ms` | Phân vị độ trễ | tất cả |
| `tokens_total`, `llm_calls_per_q`, `cost_usd_total` | Chi phí | tất cả |
| `truncated_generations` | Số lượt sinh bị cắt ở `max_tokens`; **> 0 thì không báo cáo số** | tất cả |
| `correct_abstention_by_layer` | Phần `correct_abstention` do từng lớp: `retrieval_floor` / `out_of_domain` / `model` / `guard` (cộng lại bằng `correct_abstention`) | unanswerable |
| `by_type` | Tỉ lệ từ chối và bịa theo loại câu | tất cả |
| `by_tag` | False abstention và retrieval recall theo tag | answerable |

**So khớp gold theo nội dung** (`matches`, `covers`): chunk trúng gold nếu `ref`
khớp, **hoặc** văn bản chunk **chứa** văn bản khoản gold — trọn khoản, hoặc nửa
đầu/nửa sau với khoản ≥ 20 từ bị ranh giới cửa sổ cắt ngang. So theo từ (bỏ dấu
câu, xuống dòng). Phải là *chứa* chứ không phải *trùng lặp*: bản đầu dùng tỉ lệ
trigram trùng, và vì cụm "người sử dụng lao động" có khắp nơi, một cửa sổ 1.200
ký tự bị coi là "chứa" 15–39 khoản.

## 4. Công cụ

| Lệnh | Làm gì | Gọi LLM? |
|---|---|---|
| `python -m eval.run --config configs/full.yaml --ingest data/corpus --out reports/full.json [--gate] [--split test\|dev\|all] [--as-of YYYY-MM-DD] [--corpus DIR] [--judge-threshold X]` | Chạy một cấu hình, chấm, ghi report đầy đủ | Có |
| `make eval-all` | Bốn cấu hình (mỗi cái một tiến trình, để cache NLI không ưu ái cấu hình chạy sau) + bảng | Có |
| `python -m eval.report reports/*.json` | Hai bảng markdown: metric chính và lớp phòng thủ | Không |
| `python -m eval.rejudge reports/*.json` | Chấm lại report cũ bằng thước đo hiện tại, ghi đè tại chỗ | Không |
| `python -m eval.ragas_eval reports/full.json [--limit 10]` (`make ragas`) | RAGAS: faithfulness, answer relevancy, context precision, context recall; chẩn đoán từng câu; so NLI với judge | Có (judge) |
| `python -m eval.closed_book --n 20` (`make closed-book`) | Cùng model, **không** tài liệu: RAG có mua được gì không | Có |
| `scripts/calibrate_tau.py collect\|sweep\|rescore` (`make calibrate`) | Hiệu chỉnh τ trên dev | collect: có |
| `scripts/nli_probe.py [--model] [--tau]` (`make nli-probe`) | 24 cặp thử NLI | Không |
| `scripts/sweep_floor.py` | Đánh đổi của `min_score` | Không |
| `scripts/why_abstained.py reports/full.json` | Câu **có** đáp án bị lớp nào chặn | Không |
| `scripts/hand_grade.py sample\|score` | Lấy 30 câu đã trả lời để chấm tay, rồi so với thước đo | Không |
| `scripts/check_dataset.py` | Kiểm tra dataset với corpus | Không |

### `eval/run.py` — chi tiết đáng biết

- **Khởi động model trước khi bấm giờ** (một lần `search` và một lần
  `entailment`) để câu đầu không bị tính thời gian nạp model.
- **Provider lỗi không giết cả lượt chạy**: mỗi câu thử lại 3 lần ngoài (15 s,
  30 s, 60 s); vẫn lỗi thì ghi vào `errored` và chạy tiếp.
- Cảnh báo khi τ của thước đo khác τ của guard (`[warn] judge tau ... != guard tau`).
- `--gate`: thoát mã 1 nếu `hallucination_rate > 0.10` hoặc `false_abstention > 0.15`.
  **Bỏ qua trên tập mẫu** — ngưỡng chỉ có nghĩa với dataset đầy đủ.
- `--ingest` cần thiết với mock (store trong bộ nhớ); với Qdrant đã có index thì
  dùng `--corpus data/corpus` để khỏi embed lại hàng chục phút.

### Report JSON

```
{config, dataset, split, as_of,
 generator: {provider, model},          ← thiếu cái này thì report không so sánh được
 judge: {verifier, threshold},
 metrics: {...},                         ← aggregate()
 errored: [{id, error}],
 cases: [{id, type, tags, question, gold_answer, gold_chunks,
          status, abstain_reason, answer, hallucinated,
          claims,          ← verdict của THƯỚC ĐO
          guard_claims,    ← verdict của GUARD, kể cả mệnh đề bị bỏ (nơi duy nhất thấy guard chặn nhầm)
          cited, sources: [{label, ref, score, text, article, clause}],
          latency_ms, tokens, llm_calls, cost_usd, steps}]}
```

### RAGAS — chẩn đoán từng câu

| `context_recall` | `faithfulness` | `diagnosis` | Sửa ở đâu |
|---|---|---|---|
| ≥ 0.5 | ≥ 0.8 | `ok` | — |
| ≥ 0.5 | < 0.8 | `generation_unfaithful` | prompt, guard, model |
| < 0.5 | ≥ 0.8 | `retrieval_gap` | chunking, embedding, viết lại truy vấn |
| < 0.5 | < 0.8 | `both` | sửa retrieval trước |

Và `nli_vs_judge`: `both_clean`, `both_flagged`, `only_nli_flagged` (guard khắt
khe hơn), `only_judge_flagged` (guard có thể bỏ lọt — **đọc tay từng câu**).
Judge là endpoint OpenAI-compatible bất kỳ (`JUDGE_MODEL`, `JUDGE_BASE_URL`,
`JUDGE_API_KEY`). **Chưa chạy với giám khảo thật.**

## 5. Bốn cấu hình

| Cấu hình | Floor | Guard | Chunker | Corrective | Trả lời câu hỏi |
|---|---|---|---|---|---|
| `baseline` | tắt | tắt | recursive | tắt | RAG thường làm được tới đâu? |
| `threshold` | 0.30 | tắt | recursive | tắt | "Chỉ cần một ngưỡng là đủ, cần gì NLI?" |
| `full` | 0.30 | τ 0.50 | structural | tắt | Guard đổi được gì, tốn gì? |
| `agentic` | 0.30 | τ 0.50 | structural | bật | Agentic RAG tốn thêm bao nhiêu, mua được gì? |

Lưu ý: `threshold` → `full` đổi **hai** thứ (guard và chunker), nên cột recall và
citation chịu ảnh hưởng của chunker nhiều như của guard.

## 6. Kết quả hiện có

| Report | Generator | Ghi chú |
|---|---|---|
| `reports/2026-10-12-gemini/{baseline,threshold,full,agentic}.json` | `gemini-3.1-flash-lite` | **Bảng chính của README**, 80 câu test, ~4 giờ trên CPU |
| `reports/2026-09-15/full.json` | `qwen2.5:3b` (Ollama, CPU) | 100 câu; false abstention 0.78 — model 3B gần như không trả lời |
| `reports/smoke-2026-09-11/` | Gemini | 7 câu, lượt chạy thật đầu tiên, **không phải benchmark** |
| `reports/closed-book.json` | `qwen2.5:3b` | 60 câu: không tài liệu, model trả lời cả 60, chỉ 23% mệnh đề có căn cứ trong khoản gold; với RAG chỉ trả lời 13 câu nhưng 81% mệnh đề có căn cứ |
| `reports/floor-sweep.json` | — | Đường cong của `min_score` |

Bảng chính: xem [01](01-overview.md#kết-quả-đo-được-2026-10-12). Lớp nào chặn câu
không có đáp án (tỉ lệ trên 30 câu):

| Cấu hình | floor | out of domain | model tự từ chối | guard |
|---|---|---|---|---|
| `baseline` | – | – | 0.93 | – |
| `threshold` | 0.57 | 0 | 0.40 | – |
| `full` | 0.53 | 0 | 0.40 | 0 |
| `agentic` | 0.37 | 0 | 0.53 | 0.03 |

## 7. Điểm yếu của phương pháp (đã kiểm chứng 2026-10-17)

| # | Vấn đề | Bằng chứng |
|---|---|---|
| E1 | Cột Halluc. đo nhiễu của NLI nhiều hơn đo việc bịa | Đọc tay 7 câu baseline bị chấm "bịa": `a014` (0.44), `a057` (0.19), `a052` (0.23) đúng nguyên văn luật; `a044` gần như chép gold answer mà được 0.20 |
| E2 | Không đo độ **đúng** | `gold_answer` có nhưng metric chính không dùng |
| E3 | Chưa có đối chứng độc lập | Chấm tay 30 câu và RAGAS chưa chạy |
| E4 | Mẫu nhỏ, không có khoảng tin cậy | n = 80 → nửa độ rộng CI 95% ≈ ±0.078; mọi khác biệt là 1–3 câu |
| E5 | Thiên lệch do cách tạo câu hỏi | Câu answerable sinh từ chính chunk → từ ngữ gần văn bản → recall có thể cao hơn thực tế |
| E6 | CI gate là smoke test | Mock trên 6 câu, ngưỡng bị bỏ qua |
| E7 | Metric retrieval thô | Chưa có recall@k, MRR |

Kế hoạch sửa: Sprint 1 trong [../13-sprint-plan.md](../13-sprint-plan.md).

## 8. Kỷ luật đo lường

1. Không sửa dataset sau khi xem kết quả.
2. Không báo cáo số trên dev.
3. Báo cáo cả khi kết quả xấu.
4. Cố định `--as-of` khi so sánh các lượt chạy cách xa nhau.
5. Mỗi cấu hình một tiến trình.
6. `truncated_generations > 0` thì sửa config trước, không báo cáo số.
7. Đổi prompt hoặc τ → chạy lại cả bốn cấu hình.

---

[← 07 — Guard](07-guard.md) · [Handbook](README.md) · [09 — API & giao diện →](09-api-and-ui.md)
