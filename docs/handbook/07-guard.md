# 07 — Groundedness guard

Phần lõi của dự án. Ý tưởng: một câu trả lời RAG đúng là câu trả lời mà **mọi
mệnh đề đều suy ra được từ đoạn tài liệu nó trích dẫn** — đúng định nghĩa quan
hệ *entailment* của NLI.

```
premise    = đoạn tài liệu được trích dẫn
hypothesis = một mệnh đề trong câu trả lời
score      = P(entailment)
```

Guard gồm bốn phần, chạy trong `policy.verify_claims` rồi `policy.apply_policy`:

```
văn bản model ─► claim_splitter ─► với mỗi mệnh đề:
                                     không có [Cx]  → uncited (0.0)
                                     có [Cx]        → NLIVerifier.entailment(premise ghép, mệnh đề)
                                                        luật con số → 0 nếu bịa số
                                                        max trên premise views
                                     < τ            → _recite: thử các đoạn khác đã đưa model
                  ─► supported / unsupported ─► should_regenerate? ─► apply_policy
```

## 1. Tách mệnh đề — `guard/claim_splitter.py`

`split_claims(answer) → list[Claim(text, citations)]`. Mỗi dòng xử lý riêng
(model trả lời dạng danh sách cũng hay như dạng văn xuôi):

| Bước | Xử lý | Vì sao (lỗi thật đã gặp) |
|---|---|---|
| 1 | Bỏ ký hiệu đầu dòng `-`, `*`, `•`, `+`, `1.`, `1)` | Mảnh "1." thành mệnh đề không trích dẫn |
| 2 | Xử lý ngoặc vuông không phải `[Cx]`: `[Điều 105]` và tag viết hoa `[CR1]`, `[TRẢ LỜI]` bị **bỏ**; còn lại như `[60 ngày]` chỉ **bỏ ngoặc, giữ chữ** | Lần sửa đầu xóa cả "[60 ngày]", biến câu đúng thành "tối đa là." |
| 3 | Bỏ tiền tố "Câu trả lời:" / "Trả lời:" | Model chép lại ô trả lời của prompt |
| 4 | Dời `[C1]` đặt **sau** dấu chấm vào trong câu | "Câu một. [C1] Câu hai." gán nhầm `[C1]` cho câu hai |
| 5 | Bảo vệ `Điều 35.`, `Khoản 1.`, `Điểm`, `Chương`, `Mục`, `TT`, `NĐ`, `CP`, `vd`, `v.v` (không phân biệt hoa thường) | Dấu chấm của chúng không kết thúc câu |
| 6 | Cắt câu ở `[.!?]` + khoảng trắng + chữ hoa tiếng Việt | — |
| 7 | Bỏ mảnh không có chữ cái; bỏ dòng dẫn nhập kết thúc bằng ":" không có trích dẫn | "Theo tài liệu:" từng đẩy mọi câu trả lời dạng danh sách vào vòng sinh lại |

`text` của `Claim` là câu đã bỏ mã trích dẫn; `citations` là các nhãn theo thứ
tự xuất hiện. Danh sách `_PROTECTED` phải cập nhật khi đổi corpus.

## 2. Chấm điểm — `guard/nli_verifier.py`

### Model

`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, ~280M tham số, đa
ngữ, chạy CPU. Gọi qua `transformers.pipeline("text-classification", top_k=None)`
với `truncation="only_first"` (**cắt premise, không bao giờ cắt mệnh đề**), lấy
xác suất nhãn bắt đầu bằng `entail`.

### `NLIVerifier.entailment(premise, hypothesis)` — hai lớp bọc quanh model

**Lớp 1 — luật con số** (`numbers_supported`): mọi con số trong mệnh đề phải có
trong premise, sau chuẩn hóa (`"08"` = `"8"`, `"1.000"` = `"1000"`). Không thỏa
→ trả **0.0**, không chạy model. Lý do: câu trả lời pháp luật *chính là* con số,
và NLI chấm "48 giờ → 40 giờ" tới 0.72.

**Lớp 2 — premise views** (`premise_views`): một khoản luật là tiêu đề Điều +
câu dẫn + danh sách a), b), c), hoặc vài câu nối nhau. Mệnh đề thường chỉ nhắc
lại **một mục**; đọc cả khoản, model chấm câu đúng "được ký tối đa 36 tháng" chỉ
0.46. Nên premise được tách thành nhiều "view", mỗi view **giữ tiêu đề Điều và
câu dẫn** để một mục không bị đọc tách khỏi chủ thể và điều kiện:

```
view 0: cả khoản
view i: "Điều 20. …\n<câu dẫn kết thúc bằng :>\n<mục i>"     (với mỗi mục a), b) …)
view j: "Điều 20. …\n<một câu>"                              (với mỗi câu, hoặc nửa câu tách bởi ";")
```

Điểm = **max** trên mọi view. Cái giá: "con đẻ kết hôn được nghỉ 03 ngày" tăng
từ 0.51 lên 0.80 vì mục "c) … chết: nghỉ 03 ngày" có cùng con số.

### Cache

LRU (`OrderedDict`) giới hạn `NLI_CACHE_SIZE` (4096) cặp, khóa
`sha256(premise‖hypothesis)`, có `threading.Lock` vì verify chạy trên pool luồng.
Sinh lại kiểm tra lại phần lớn các cặp cũ nên cache có ích.

### `MockVerifier`

Điểm = tỉ lệ token của mệnh đề có trong premise. Đủ để chạy policy đầu-cuối; vô
dụng như tín hiệu thật — đúng như tên gọi.

## 3. Premise cho một mệnh đề — `policy._cited_premises`

| Mệnh đề trích | Premise được chấm |
|---|---|
| 1 đoạn | đoạn đó |
| 2 đoạn | 2 đoạn nối lại |
| ≥ 3 đoạn | tất cả nối lại **và** từng cặp (3 khoản nối lại dễ vượt 512 token; khoản bị cắt thường chính là khoản cần) |

## 4. Sửa trích dẫn — `policy._recite`

Model nhỏ hay trích `[C1]` cho nội dung của `[C2]`. Khi điểm `< τ`, guard thử
**từng đoạn khác đã đưa cho model**; đoạn tốt nhất đạt τ thì chuyển trích dẫn
sang đó, nhãn gốc giữ ở `cited_as` (UI hiển thị). Không có gì ngoài context lọt
qua được: mệnh đề vẫn phải được **một** đoạn đã truy xuất chứng minh. Mệnh đề
không có trích dẫn nào thì **không** được sửa — đó vẫn là vi phạm hợp đồng prompt.

## 5. Chính sách — `policy.py`

| Tình huống | Hành động |
|---|---|
| Model trả đúng câu từ chối (`is_abstention`) | `abstained`, `reason: model`; không kiểm chứng, **không sinh lại** |
| Mọi mệnh đề `≥ τ` | `answered` |
| Có mệnh đề `< τ` hoặc `uncited`, còn lượt (`max_regenerations: 1`) và còn ngân sách | Sinh lại kèm danh sách mệnh đề sai |
| Sinh lại mà model từ chối, lượt trước có mệnh đề tốt | Giữ mệnh đề đã kiểm chứng → `partial` |
| Sinh lại mà model từ chối, không có mệnh đề tốt | `abstained`, `reason: guard` |
| Hết lượt, còn mệnh đề tốt và còn mệnh đề xấu | `drop_claim` → `partial`; `abstain_all` → `abstained` |
| Không còn mệnh đề tốt (kể cả văn bản rỗng sau khi gỡ trích dẫn bịa) | `abstained`, `reason: guard` |
| Không có mệnh đề nào ("[C1]" trơ trọi) | Sinh lại với phản hồi riêng: "chỉ gồm mã trích dẫn, không có câu văn nào" |

Câu trả lời cuối = các mệnh đề `supported` ghép lại, mỗi câu kèm `[Cx]` (sau
`_recite` có thể khác nhãn model viết). Response luôn chứa **mọi** mệnh đề kèm
điểm và verdict.

Hai quyết định nhỏ nhưng quan trọng:

- **Câu từ chối không phải mệnh đề.** Trước đây nó không có trích dẫn nên bị tính
  `uncited`: guard sinh lại vô ích, còn baseline bị tính "trả lời và bịa" đúng lúc
  nó từ chối đúng.
- **Guard tắt thì không lọc gì.** `apply_policy` với guard tắt trả văn bản model
  nguyên vẹn; lọc ở đây sẽ cho baseline hưởng một phần lợi ích của guard và làm
  bảng so sánh vô nghĩa.

## 6. Ngưỡng τ — hiệu chỉnh trên tập dev

Quy trình (`scripts/calibrate_tau.py`, `make calibrate`):

1. `collect`: trả lời 20 câu dev bằng truy xuất của `full` và `baseline`, guard
   tắt để giữ mọi mệnh đề; chấm mỗi mệnh đề với đoạn nó trích và với đoạn khác
   tốt nhất → `reports/tau-dev-claims.json` (kèm premise để gán nhãn bằng đọc).
2. Gán nhãn tay `"grounded": true | false`.
3. `sweep`: mô phỏng guard ở từng τ → `reports/tau-sweep.json`,
   `docs/img/tau-curve.svg`. Không gọi LLM.
4. `rescore`: sau khi đổi verifier, chấm lại rồi sweep.

### Kết quả (2026-09-17, 23 mệnh đề, qwen2.5:3b)

| τ | Mệnh đề sai bị chặn (6) | Mệnh đề đúng bị chặn nhầm (17) |
|---|---|---|
| **0.50** | **0%** | **0%** |
| 0.60 | 0% | 6% |
| 0.70 | 0% | 24% |
| 0.75 | 17% | 35% |
| 0.90 | 67% | 47% |

**Không có τ nào tách được hai nhóm.** Cả sáu mệnh đề sai được ≥ 0.70: đảo điều
kiện, bỏ điều kiện, đổi chủ thể nam → nữ, lấy con số của mục bên cạnh (40 thay 30
ngày, cả hai đều có trong khoản), nhầm chế độ, "15 tháng" thay "15 năm". τ chọn
**0.50**: thấp nhất mà probe vẫn đúng như ở 0.60, và không chặn nhầm câu đúng nào
trên dev. Nhãn gán bởi trợ lý AI, lý do từng nhãn trong `tau-dev-claims.json`.

## 7. Probe NLI — `scripts/nli_probe.py` (`make nli-probe`)

24 cặp (premise là khoản luật thật). Số cặp guard xử lý sai ở τ 0.60 (0.50 giống hệt):

| Nhóm (số cặp) | mDeBERTa đọc cả khoản | mDeBERTa + views + luật số | xlm-roberta-large + views + luật số |
|---|---|---|---|
| Câu đúng, khoản ngắn (3) | 0 | 0 | 0 |
| Câu đúng, một mục của khoản dài (7) | 1 | **0** | 1 |
| Đổi con số (4) | 1 | **0** | 0 |
| Con số của mục bên cạnh (2) | 1 | 2 | 2 |
| Phủ định (1) | 0 | 0 | 0 |
| Đổi chủ thể (2) | 1 | 1 | 1 |
| Đổi/bỏ điều kiện, near-miss (5) | 2 | 2 | 4 |
| **Tổng sai** | **6** | **5** | **8** |

Model lớn gấp đôi còn tệ hơn ở nhóm khó nhất → giữ mDeBERTa.

## 8. Guard sai ở đâu

| Loại lỗi | Bắt được? | Bằng gì |
|---|---|---|
| Mệnh đề không trích dẫn, trích nhãn không tồn tại | ✅ | Luật, không cần model |
| Đổi con số | ✅ | Luật con số, không phải NLI |
| Câu đúng diễn đạt lại một mục của khoản dài | ✅ (không chặn nhầm) | Premise views |
| Lấy con số của mục bên cạnh trong cùng khoản | ❌ | Con số *có* trong premise |
| Đổi chủ thể ("người sử dụng lao động" ↔ "người lao động") | ❌ | NLI thiên về trùng từ vựng |
| Thêm/bỏ điều kiện, near-miss | ❌ | Loại khó nhất của dataset |
| Câu đúng cần suy luận nhiều bước | ❌ (chặn nhầm) | NLI cho `neutral` → tính vào `false_abstention` |
| Model thay con số bằng mã trích dẫn ("ít nhất [C1] ngày") | ❌ | Bỏ mã thì không còn số để kiểm; đã sửa bằng **prompt** (quy tắc 2) |

**Kết luận trung thực:** trên tập dev, NLI không bắt được lỗi nào trong số lỗi
model thật sự mắc. Phần bảo vệ thật sự là ba dòng ✅ đầu, và hai trong ba không
dùng NLI. Chi phí của guard là `false_abstention` — chỉ số bắt buộc báo cáo cạnh
`hallucination_rate`.

## 9. Vì sao NLI mà không phải LLM judge

[ADR-0001](../adr/0001-nli-over-llm-judge.md): NLI chạy local miễn phí,
~50–200 ms/cặp trên CPU, tất định, **khác họ** với model sinh (LLM chấm LLM là
dùng đúng loại model đã bịa để phát hiện nó bịa), cho một con số hiệu chỉnh ngưỡng
được. LLM judge vẫn được dùng ở một chỗ: RAGAS trong eval, làm ý kiến thứ hai.

## 10. Sửa guard thì phải làm gì

1. Thêm/sửa test trong `tests/test_policy.py`, `test_nli_verifier.py`,
   `test_claim_splitter.py`.
2. `make nli-probe` — không được tệ hơn.
3. `python scripts/calibrate_tau.py rescore` rồi `sweep` nếu đổi verifier.
4. `python -m eval.rejudge reports/2026-10-12-gemini/*.json` nếu đổi thước đo
   (không gọi LLM), hoặc `make eval-all` nếu đổi hành vi guard.
5. **Prompt và guard đi cùng nhau**: nới prompt thì tỉ lệ guard chặn đổi theo.

---

[← 06 — Ingest & retrieval](06-ingest-and-retrieval.md) · [Handbook](README.md) · [08 — Đánh giá →](08-evaluation.md)
