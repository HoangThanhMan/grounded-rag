# 07 — Kế hoạch đánh giá

Nếu chỉ làm được một thứ trong ba tuần, làm cái này.

## Tập đánh giá

100 câu hỏi tự gán nhãn:

| Loại | Số câu | Kiểm tra điều gì |
|---|---|---|
| `answerable` | 63 | Trả lời đúng và trích dẫn đúng |
| `unanswerable_out_of_scope` | 15 | Có biết im lặng khi câu hỏi thuộc luật khác |
| `unanswerable_false_premise` | 13 | Có bịa ra quy định không tồn tại |
| `unanswerable_near_miss` | 9 | **Bẫy khó nhất** — đúng chủ đề, sai chi tiết |

Con số ban đầu là 60/15/15/10. Lượt kiểm tra chéo ngày 2026-09-17 chuyển ba câu
`unanswerable` thành `answerable` vì corpus bác được tiền đề của chúng — bác
tiền đề kèm trích dẫn *là* câu trả lời, không phải từ chối
([LABELING.md](../eval/dataset/LABELING.md)).

Tỉ lệ xấp xỉ 60/40 là cố ý. Benchmark RAG thông thường chỉ có câu trả lời được, nên
không bao giờ đo được điều quan trọng nhất: model có biết dừng lại không.

`near_miss` là loại model bịa nhiều nhất. Thiếu thời gian thì cắt `out_of_scope`
trước, giữ nguyên `near_miss`.

Trong các câu `answerable`, gắn `tags` cho 11 câu `multi_part` (nhiều ý)
và 11 câu `colloquial` (cách nói đời thường). Đây là hai lát cắt mà vòng truy
xuất sửa lỗi sinh ra để xử lý; một con số trung bình sẽ che mất tác dụng của nó.

Quy trình gán nhãn: [eval/dataset/LABELING.md](../eval/dataset/LABELING.md).

**Tách dev/test.** 20 câu mang `"split": "dev"`, lấy phân tầng theo loại, và chỉ
dùng để hiệu chỉnh τ (`scripts/calibrate_tau.py`). `eval.run` mặc định
`--split test`, tức chấm trên 80 câu còn lại. Báo cáo một con số trên tập dev
là chấm trên chính dữ liệu đã dùng để chọn ngưỡng.

## Công cụ đo: một thước cho mọi cấu hình

`hallucination_rate` được chấm **sau khi chạy**, trên văn bản trả lời cuối cùng,
bằng cùng một NLI verifier ở cùng một ngưỡng (`ENTAILMENT_THRESHOLD`), bất kể
cấu hình đó có bật guard hay không. Pipeline của `baseline` không kiểm chứng gì
(nó không trả chi phí của guard), nhưng câu trả lời của nó bị chấm bằng đúng cái
thước đo `full`.

Bản đầu chấm baseline bằng một verifier luôn trả "supported". Khi đó cột Halluc.
của baseline chỉ đếm câu thiếu trích dẫn, và bảng so sánh nghiêng về guard mà
không ai thấy.

Hai quy tắc đo nữa:

- **Model tự từ chối là từ chối.** Câu trả lời đúng bằng câu từ chối của prompt
  được tính vào `abstained` (`abstain_reason: model`), không phải một mệnh đề
  không trích dẫn.
- **Gold so khớp theo nội dung.** Chunk trúng gold nếu `ref` khớp, hoặc nó
  *chứa* khoản gold: trọn khoản, hoặc nửa đầu/nửa sau với khoản dài ≥ 20 từ bị
  ranh giới cửa sổ cắt ngang. Không có quy tắc thứ hai thì chunk `recursive`
  không bao giờ trúng và so sánh hai chunker bị gian lận từ thiết kế. Phải là
  *chứa* chứ không phải *trùng lặp*: bản đầu dùng tỉ lệ trigram trùng, và vì
  cụm "người sử dụng lao động" có ở khắp nơi, một cửa sổ 1.200 ký tự bị coi là
  "chứa" 15–39 khoản — `citation_precision` của cấu hình recursive bị thổi phồng.
- **Premise cùng cỡ cho mọi cấu hình.** Mỗi mệnh đề được chấm với chunk nó
  trích, với từng khoản mà chunk đó chứa trọn, với từng cặp khoản liền kề
  trong đó (một câu hay gộp hai khoản: "08 giờ/ngày, hoặc 10 giờ nếu theo
  tuần"), và với các chunk trích dẫn ghép lại; lấy điểm cao nhất
  (`eval/instrument.py`). Chunk structural được chấm đúng như được trích: trích
  một khoản cho câu cần hai khoản là trích thiếu. Lần chạy thật đầu tiên cho
  thấy vì sao: chunk `recursive` dài 565–680 token, quá 512 token mà mDeBERTa
  đọc được. Cùng một mệnh đề đúng được 0.02–0.32 khi chấm với cửa sổ đó và
  0.85–0.97 khi chấm với khoản nằm trong nó. Chấm thẳng trên cửa sổ thì
  baseline "bịa" 57% — một con số đo kích thước chunk, không đo guard.

Đổi thước đo hoặc ngưỡng thì chấm lại report cũ, không cần gọi lại LLM:
`python -m eval.rejudge reports/*.json`.

Thước đo đã công bằng về kích thước premise vẫn có giới hạn của chính model
NLI: mệnh đề diễn đạt lại một khoản dài có điều kiện (Điều 105:2 — "theo tuần
thì không quá 10 giờ/ngày") chỉ được ~0.4 dù đúng. Đó là lý do phải có chấm tay
và RAGAS bên cạnh.

## Chỉ số

| Chỉ số | Định nghĩa | Hướng |
|---|---|---|
| `hallucination_rate` | % câu trả lời có ≥1 mệnh đề không được chứng minh (theo công cụ đo ở trên) | ↓ |
| `correct_abstention` | % câu không-trả-lời-được mà hệ thống đúng là từ chối | ↑ |
| `false_abstention` | % câu trả lời được nhưng hệ thống từ chối | ↓ |
| `citation_precision` | Trong các chunk được trích dẫn *ở câu trả lời cuối*, bao nhiêu là chunk chuẩn — tính trên câu trả lời được và đã được trả lời | ↑ |
| `citation_recall` | Trong các chunk chuẩn, bao nhiêu được trích dẫn — cùng tập câu | ↑ |
| `retrieval_recall` | Trong các chunk chuẩn, bao nhiêu lọt vào ngữ cảnh đưa cho LLM | ↑ |
| `latency_p50/p95_ms` | Độ trễ | ↓ |
| `tokens_total`, `llm_calls_per_q`, `cost_usd_total` | Chi phí | ↓ |
| `correct_abstention_by_layer` | Phần `correct_abstention` do từng lớp chặn: floor / out_of_domain / model / guard | — |
| `by_type`, `by_tag` | Các chỉ số trên tách theo loại câu và theo tag | — |

Thêm, chấm thủ công trên 30 câu mẫu:

- `answer_correctness` — câu trả lời có đúng nội dung không (guard chỉ kiểm tra
  *có căn cứ*, không kiểm tra *đúng*; hai chuyện khác nhau và phải đo riêng)

> Cảnh báo quan trọng: `hallucination_rate` đo bằng cùng họ model với NLI guard
> là **đo vòng tròn**. Hai đối chứng độc lập: chấm tay 30 câu mẫu, và RAGAS
> (bên dưới). Ghi cả ba con số trong README, đừng giấu con số chấm tay.

## RAGAS — ý kiến thứ hai

`eval/ragas_eval.py` chấm lại một report bằng bốn chỉ số RAGAS, với **LLM làm
giám khảo** — khác họ với NLI, nên độc lập với guard:

| Chỉ số | Bề mặt | Câu hỏi |
|---|---|---|
| `faithfulness` | Sinh | Câu trả lời có bám đúng ngữ cảnh được đưa không? |
| `answer_relevancy` | Sinh | Có trả lời đúng câu được hỏi không? |
| `context_precision` | Truy xuất | Đoạn hữu ích có nằm ở thứ hạng cao không? |
| `context_recall` | Truy xuất | Ngữ cảnh có đủ thông tin trong đáp án chuẩn không? (cần `gold_answer`) |

Chỉ chấm câu có trả lời (`answered` / `partial`). Câu từ chối không có gì để
RAGAS chấm; chi phí của nó đã nằm trong `false_abstention`.

**Chẩn đoán từng câu** — đọc recall và faithfulness cùng nhau:

| `context_recall` | `faithfulness` | `diagnosis` | Sửa ở đâu |
|---|---|---|---|
| ≥ 0.5 | ≥ 0.8 | `ok` | — |
| ≥ 0.5 | < 0.8 | `generation_unfaithful` | Tìm đúng tài liệu, model không bám: prompt, guard, model |
| < 0.5 | ≥ 0.8 | `retrieval_gap` | Model bám đúng một ngữ cảnh thiếu: chunking, embedding, viết lại truy vấn |
| < 0.5 | < 0.8 | `both` | Sửa retrieval trước |

**NLI vs giám khảo:** mỗi câu được xếp vào `both_clean`, `both_flagged`,
`only_nli_flagged` (guard khắt khe hơn), `only_judge_flagged`. Nhóm cuối cùng là
những câu guard có thể đã bỏ lọt — **đọc từng câu bằng tay**.

```bash
export JUDGE_MODEL=gemini-2.5-flash
export JUDGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export JUDGE_API_KEY=...
make ragas          # reports/<config>.ragas.json cho từng cấu hình
```

## Bốn cấu hình so sánh

| Cấu hình | Ngưỡng retrieval | Guard | Chunker | Truy xuất sửa lỗi |
|---|---|---|---|---|
| `baseline` | tắt | tắt | recursive | tắt |
| `threshold` | 0.30 | tắt | recursive | tắt |
| `full` | 0.30 | bật, τ hiệu chỉnh | structural | tắt |
| `agentic` | 0.30 | bật, τ hiệu chỉnh | structural | bật ([ADR-0005](../docs/adr/0005-corrective-retrieval-loop.md)) |

Retrieval (hybrid + rerank) giống nhau ở mọi cấu hình, nên bảng cô lập được tác
dụng của floor, guard và vòng sửa lỗi.

`threshold` tồn tại để trả lời câu hỏi hiển nhiên nhất về thiết kế này: *"Có
phải chỉ cần một ngưỡng đơn giản là đủ không, cần gì NLI?"* — có số liệu để
trả lời.

`agentic` trả lời câu hỏi thứ hai: *"Agentic RAG tốn thêm bao nhiêu, và mua được
gì?"* — so với `full` trên `false_abstention` và `retrieval_recall` (nhất là tag
`multi_part`, `colloquial`), đổi lại `llm_calls_per_q` và `p95`. Phải xem cả
`correct_abstention` của `near_miss`: planner viết lại có thể "sửa" một câu bẫy
thành câu trả lời được.

Ablation thêm, không đưa vào bảng chính: `hybrid: false` (chỉ dense) để đo BM25
mua được gì.

## Cách chạy

```bash
make eval-all          # bốn cấu hình + hai bảng markdown
python -m eval.run --config configs/full.yaml --out reports/full.json --gate
python -m eval.run --config configs/full.yaml --as-of 2026-09-01   # cố định ngày đọc luật
```

`--gate` thoát mã 1 khi vượt ngưỡng — đây là cách CI dùng. Report lưu đầy đủ
từng câu (ngữ cảnh, câu trả lời, verdict, trace), dùng cho phân tích lỗi và cho
RAGAS.

## Ngưỡng chặn trong CI

```python
DEFAULT_GATES = {"hallucination_rate": 0.10, "false_abstention": 0.15}
```

CI chạy trên tập mẫu với provider `mock` (nhanh, không tốn tiền, không cần key),
cho cả `full` và `agentic`. Tập đầy đủ chạy tay trước mỗi lần cập nhật README.

## Kỷ luật

1. **Không sửa tập đánh giá sau khi đã xem kết quả.** Nếu buộc phải sửa vì phát
   hiện nhãn sai, ghi vào changelog và chạy lại cả bốn cấu hình.
2. **Tập dev (20 câu hiệu chỉnh τ) không được tính vào số báo cáo.**
3. **Báo cáo cả khi kết quả xấu.** Nếu guard hay vòng sửa lỗi không cải thiện
   được gì, viết ra và phân tích vì sao. Một dự án nói "cách này chỉ hiệu quả
   với loại lỗi A, không hiệu quả với loại B" đáng tin hơn nhiều một dự án toàn
   màu hồng.
4. **Cố định `--as-of`** khi so sánh các lần chạy cách xa nhau về thời gian.

## Bảng cần điền vào README

| Configuration | Halluc. ↓ | Correct abst. ↑ | False abst. ↓ | Cite prec. ↑ | Retr. recall ↑ | LLM calls/q | p95 (ms) |
|---|---|---|---|---|---|---|---|
| baseline | | | | | | | |
| threshold | | | | | | | |
| full | | | | | | | |
| agentic | | | | | | | |

Kèm một dòng: guard đổi được bao nhiêu điểm hallucination và trả giá bao nhiêu
điểm false abstention; vòng sửa lỗi gỡ lại được bao nhiêu false abstention với
giá bao nhiêu lời gọi LLM. Và bảng thứ hai — lớp nào chặn câu không-trả-lời-được:

| Configuration | retrieval_floor | out_of_domain | model | guard |
|---|---|---|---|---|


## Ablation: có retrieval và không có retrieval

Bảng bốn cấu hình chỉ so các kiểu retrieval với nhau. Nó không trả lời câu hỏi
đứng trước tất cả: **cùng model đó, không đưa tài liệu gì, nó trả lời thế nào?**
Thiếu con số này thì "RAG hoạt động" là một giả định chứ không phải kết luận.

```bash
python -m eval.closed_book --n 60 --threshold 0.6 --out reports/closed-book.json
```

### Vì sao không dùng thước đo của benchmark

`judge_claims` chấm mệnh đề dựa trên **đoạn mà câu trả lời trích dẫn**. Trả lời
chay không có trích dẫn nào, nên mọi mệnh đề thành `uncited` và
`hallucination_rate` = 1.0 — con số đó đo "không trích dẫn", không đo "sai".
So như vậy là gian lận với phía không có RAG.

Công cụ này chấm **cả hai phía bằng cùng một thứ**: khoản luật gold của chính
câu hỏi đó.

| Chỉ số | Nghĩa |
|---|---|
| `grounded_claims` | tỉ lệ mệnh đề được khoản gold chứng minh (NLI) |
| `gold_numbers_present` | số trong đáp án chuẩn có xuất hiện trong câu trả lời |
| `answered` | có trả lời hay từ chối |

Prompt của phía chay **cố ý khác** prompt RAG: prompt RAG bắt trích dẫn và đưa
sẵn câu từ chối, dùng nó khi không có tài liệu thì ép model phải từ chối.

### Đọc kết quả cho đúng

**`grounded_claims` thiên vị RAG tới mức gần như tautology.** Câu trả lời RAG
được dựng từ chính chunk được trích, mà chunk đó thường là gold chunk — nó gần
như không thể không "grounded". Trả lời chay thêm bối cảnh ("Theo khoản 2 Điều
20...") thì mệnh đề đó đúng nhưng không nằm trong văn bản khoản luật, nên bị
chấm là thiếu căn cứ. Hai cột đáng tin là `answered` và `gold_numbers_present`.

**`gold_numbers_present` quan trọng hơn vẻ ngoài.** Đáp án pháp luật xoay quanh
"45 ngày", "08 giờ", "85%". Đổi số thì câu vẫn trôi chảy, vẫn đúng ngữ pháp,
chỉ sai luật — và đó đúng là chỗ NLI yếu nhất (xem probe ngày 9 trong [08]).
Kiểm tra số bằng luật đơn giản bắt được thứ NLI bỏ lọt, và không tốn model nào.

### Kết quả 2026-09-15 — và vì sao không có một câu trả lời chung

Chạy hai lần với hai model khác nhau, kết luận **trái ngược**:

- `gemini-3.1-flash-lite`, 8 câu: trả lời chay đáp đủ 8/8 và lấy đúng **100%**
  số trong đáp án chuẩn; RAG chỉ đáp 4/8, đúng 67%. Model đã thuộc các điều
  luật phổ biến; retrieval chủ yếu lấy đi câu trả lời đúng.
- `qwen2.5:3b-instruct`, 60 câu, τ = 0.60 (`reports/closed-book.json`):

  | | trả lời chay | RAG (`full`) |
  |---|---|---|
  | Số câu trả lời | 60 | **13** |
  | Số gold lấy đúng, **trên 13 câu RAG trả lời** | 3/17 = 0.18 | 11/17 = **0.65** |
  | Mệnh đề có căn cứ, trên 13 câu đó | 6/14 = 0.43 | 13/16 = 0.81 |
  | Số gold lấy đúng, trên 47 câu RAG từ chối | 7/84 = **0.08** | — |

  Trạng thái RAG: 44 `abstained`, 13 `answered`, 3 `no_context`.

  Trên cùng tập câu hỏi, **RAG chính xác gấp 3,6 lần** (0.65 so với 0.18). Nhưng
  nó chỉ trả lời 22% số câu, và 44 câu bị từ chối đều **có đáp án rõ ràng trong
  corpus** — đã kiểm chứng bằng `make check-dataset`. Đó là guard hỏng, không
  phải guard làm đúng việc. Trên 47 câu ấy, trả lời chay nói sai **77 con số**
  mà lẽ ra tra được.

**"RAG có đáng không" phụ thuộc vào model, không phải là một hằng số.** Với
model mạnh trên domain phổ biến, retrieval có thể là chi phí ròng. Với model
yếu hoặc văn bản mới, nó là thứ ngăn một câu bịa nói ra đầy tự tin.

Hai cảnh báo khi trích kết quả này:

1. Tám câu Gemini nghiêng về các điều nổi tiếng (Điều 17, 20, 26, 35) — đúng
   phần model thuộc nhất. Luật BHXH 2024 hiệu lực 2025-07-01, nhiều khả năng
   nằm ngoài dữ liệu huấn luyện, là phép thử sòng phẳng hơn.
2. Phép so sánh này chỉ dùng 60 câu **có** đáp án. Nó chưa chạm tới 40 câu
   **không** có đáp án — nơi model thuộc bài sẽ bịa còn sàn truy xuất chặn
   được. Muốn công bằng phải chạy cả tập 100 câu.

## Hiệu chỉnh sàn truy xuất

`min_score` quyết định LLM có được gọi hay không. Retrieval là tất định nên một
lượt quét chấm được mọi ngưỡng cùng lúc, **không tốn lời gọi LLM nào**:

```bash
python scripts/sweep_floor.py --out reports/floor-sweep.json
```

Kết quả 2026-09-15 trên 100 câu, chunker `structural`:

| `min_score` | câu có đáp án tới LLM | gold vượt sàn | câu vô đáp án bị chặn |
|---|---|---|---|
| 0.05 | 0.967 | 0.967 | 0.350 |
| 0.10 | 0.950 | 0.950 | 0.425 |
| **0.30** (hiện tại) | **0.950** | **0.950** | **0.475** |
| 0.50 | 0.950 | 0.933 | 0.625 |
| 0.70 | 0.917 | 0.900 | 0.725 |

Từ 0.1 đến 0.3 **không có gì thay đổi** — ngưỡng hiện tại nằm giữa một vùng
phẳng, hạ xuống không mua được gì. Chỉ 3/60 câu có đáp án bị gold rơi dưới 0.30.

Phát hiện thật nằm ở phân bố: câu **không** có đáp án có trung vị top score
**0.340**, cao nhất 0.970. Một nửa số câu vô đáp án vẫn được reranker chấm trên
ngưỡng — cross-encoder tìm được đoạn "nghe hợp lý" cho cả câu không có đáp án.
Sàn truy xuất không thể tự làm việc này; đó là lý do guard tồn tại.

Hệ quả ngược với trực giác: **nên cân nhắc nâng ngưỡng, không phải hạ.** Từ
0.30 lên 0.50 chặn thêm 15 điểm câu vô đáp án mà chỉ mất 1,7 điểm gold, và câu
bị sàn chặn không tốn lời gọi LLM nào.
