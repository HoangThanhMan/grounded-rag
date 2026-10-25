# 09 — Runbook

## Cài đặt

```bash
cd ~/Data/project/grounded-rag
python -m venv .venv && source .venv/bin/activate

make install        # chỉ runtime, đủ để chạy test và mock pipeline
make dev-install    # thêm torch/transformers/ragas - nặng, vài GB

cp .env.example .env
```

Máy không có GPU: cài torch bản CPU **trước** `make dev-install`, nếu không pip
kéo bản CUDA nặng vài GB mà không dùng được:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Chạy nhanh, không cần API key

Provider `mock` dùng embedder hash + store in-memory + LLM giả. Không tải một
model nào. Dùng cho test, CI, và để người khác clone về chạy thử ngay.

```bash
make test                    # toàn bộ unit test
uvicorn grounded_rag.api.main:app --reload
curl localhost:8000/healthz
```

## Chạy thật

```bash
make up                                  # qdrant :6333, langfuse :3000
# sửa .env: LLM_PROVIDER=gemini | ollama | vllm | openai | anthropic, điền key
make corpus                              # Bộ luật LĐ 2019 + Luật BHXH 2024 từ Công báo
make ingest                              # index cả hai chunker
make run                                 # API + UI ở http://localhost:8000
```

Đổi chunker hoặc sửa corpus nhiều: `python -m grounded_rag.ingest.pipeline
--config configs/full.yaml --recreate` để chunk cũ không nằm lẫn chunk mới.

**RAM** (đo trên CPU i7-11800H, 16 luồng): ingest cần ~3.6 GB (bge-m3, 1.241
chunk structural mất 4 phút 20 giây); truy vấn nạp cả bge-m3,
bge-reranker-v2-m3 và mDeBERTa, đỉnh ~4.5 GB. Máy 8 GB: đóng trình duyệt trước
khi chạy, nếu không máy sẽ swap tới mức treo.

**Độ trễ trên CPU:** bước `retrieve` mất 5–6 giây với chunk structural và ~10
giây với chunk recursive — gần như toàn bộ là cross-encoder rerank 20 ứng viên.
Muốn nhanh hơn: giảm `rerank_candidates`, hoặc chạy reranker trên GPU.

### Xem trace trên Langfuse

```bash
make up                                  # langfuse :3000 chờ Postgres healthy rồi mới chạy
.venv/bin/pip install -e ".[obs]"        # SDK v2: server là langfuse:2, SDK v3+ không nói chuyện được
```

Mở `http://localhost:3000`, đăng ký, tạo project, chép cặp key vào `.env`
(`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`), rồi `make run`. Mỗi câu hỏi là
một trace `answer`, gắn tag theo config và status. Export là best effort: key
sai hay SDK sai phiên bản chỉ ghi một dòng warning, câu trả lời vẫn ra — nên
nếu không thấy trace, tìm `langfuse export failed` trong log trước.

Không muốn đăng ký trên trình duyệt: server `langfuse:2` (đã thử trên 2.95) nhận các
biến `LANGFUSE_INIT_*` (org, project, key, user) và tự tạo tất cả khi khởi
động lần đầu — đặt chúng trong một file compose override, không sửa
`docker-compose.yml`.

### Dùng Ollama (chi phí bằng 0)

```bash
ollama pull qwen2.5:7b
# .env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
```

### Dùng vLLM (cần GPU NVIDIA)

```bash
make up-gpu                              # thêm service vllm :8001
# .env
LLM_PROVIDER=vllm
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ
```

### Dùng Gemini

```bash
# .env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
```

Gọi qua endpoint tương thích OpenAI của Gemini, dùng chung client với vLLM và
Ollama.

### Kiểm tra NLI với tiếng Việt (ngày 9)

```bash
python scripts/nli_probe.py              # in P(entail) từng cặp, số cặp guard xử lý sai
```

## Chạy benchmark

```bash
make eval-all                            # bốn cấu hình + hai bảng markdown
python -m eval.run --config configs/full.yaml --ingest data/corpus \
    --out reports/full.json --gate
make ragas                               # ý kiến thứ hai, cần JUDGE_* - docs/07
python -m eval.ragas_eval reports/full.json --limit 10   # khi giám khảo bị giới hạn quota
```

**Mặc định chấm trên 80 câu `test`.** 20 câu `dev` chỉ dùng để hiệu chỉnh τ;
`--split dev` hoặc `--split all` có ích khi gỡ lỗi, nhưng một con số báo cáo từ
đó là chấm trên chính dữ liệu đã chọn ngưỡng.

**`--corpus` thay vì `--ingest` khi chỉ mục đã có.** `--ingest` nhúng lại toàn
bộ corpus bằng bge-m3 trước mỗi cấu hình; trên CPU đó là hàng chục phút nhân
bốn. Nếu Qdrant đã có sẵn collection (`curl localhost:6333/collections`), dùng
`--corpus data/corpus` — nó chỉ dựng `ClauseIndex` để giải gold ref:

```bash
for c in baseline threshold full agentic; do
  python -m eval.run --config configs/$c.yaml --corpus data/corpus \
      --out reports/$c.json --split test || break
done
python -m eval.report reports/{baseline,threshold,full,agentic}.json
```

Hai thư mục corpus, khác nhau có chủ đích:

| Thư mục | Trong git | Dùng để |
|---|---|---|
| `data/corpus/` | không | Corpus thật, dùng khi chạy benchmark đầy đủ |
| `data/sample_corpus/` | có | Vài điều luật, đủ để CI và người mới clone chạy thử |

`--gate` **không chặn** khi đang chạy trên `questions.sample.jsonl`. Ngưỡng chỉ
có nghĩa khi đã có tập 100 câu thật — CI xanh từ ngày đầu, và đỏ đúng lúc nó
nên đỏ.

## Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: sentence_transformers` / `transformers` / `torch` | Provider thật cần model thật, thuộc extra `models` | `make dev-install`, hoặc `LLM_PROVIDER=mock` |
| `ModuleNotFoundError: grounded_rag` khi chạy `python -m eval.run` (pytest vẫn xanh) | Repo đã bị chuyển thư mục: bản cài editable trong `.venv` vẫn trỏ tới `src/` ở chỗ cũ. pytest không bị vì tự thêm `src` vào `pythonpath` | `.venv/bin/python -m pip install --no-deps -e .` |
| Lỗi khởi động `llm_provider ... Input should be` | Tên provider sai chính tả — cố tình không rơi về mock | Sửa `LLM_PROVIDER` trong `.env` |
| API trả `503` | Provider LLM không phản hồi sau khi đã thử lại | Kiểm tra key, `*_BASE_URL`, Ollama/vLLM có đang chạy không |
| `POST /ingest` trả `403` / `401` / `400` | Endpoint tắt khi chưa đặt `ADMIN_API_KEY` (403); thiếu/sai header `X-API-Key` (401); `source` không nằm dưới `DATA_ROOT` (400) | Đặt `ADMIN_API_KEY` cho server và gửi cùng key; với `make seed`: `ADMIN_API_KEY=dev make seed`. Muốn xoá index thì dùng CLI `--recreate` |
| Claude trả `400` nhắc tới `temperature` | Opus 4.7 trở đi từ chối mọi `temperature`; Sonnet 5.x, Haiku 5.5 từ chối giá trị khác mặc định | Mặc định không gửi. Chỉ đặt `ANTHROPIC_SEND_TEMPERATURE=true` cho model còn nhận (dòng 4.5/4.6) |
| `/healthz` chậm khi đang tải nặng | Không còn xảy ra: lời gọi model chạy trên pool riêng (`compute.py`). Nếu thấy lại, có chỗ gọi model đồng bộ ngoài `run_model` | `tests/test_concurrency.py` bắt lỗi này |
| Ingest xong `written=0` | Chunk đã có trong chỉ mục (đúng như thiết kế) | Đổi corpus, hoặc xoá collection nếu muốn dựng lại |
| Eval trả `no_context` cho mọi câu | Đang dùng `InMemoryStore` (provider `mock`): store sống trong một process, ingest ở process khác không thấy được | Thêm `--ingest data/sample_corpus` vào lệnh eval |
| Mọi câu đều `no_context` | `min_score` quá cao so với thang điểm reranker (cả `mock` lẫn thật đều là 0–1) | Xem `meta.steps[0].detail.top_score`, hạ ngưỡng trong `configs/*.yaml` |
| Mọi câu đều `no_context`, kể cả câu dễ | `as_of` rơi ngoài `effective_date`/`expiry_date` trong front matter | Kiểm tra ngày trong front matter, hoặc truyền `as_of` |
| Kết quả retrieval lẫn chunk kiểu cũ | Đã đổi chunker hoặc đổi cách cắt mà chưa dựng lại index | Ingest với `--recreate` |
| Câu trả lời bị cụt giữa câu, guard chặn vì "không trích dẫn"; `meta.steps` có `truncated: true`, eval có `truncated_generations > 0` | Model có chế độ "thinking" tiêu phần lớn `max_tokens` cho suy nghĩ ẩn. Đo được: `gemini-3.5-flash` với `reasoning_effort=low` dùng ~490 token suy nghĩ, câu trả lời dừng sau 21 token | `LLM_REASONING_EFFORT=none`, hoặc model không thinking (`gemini-3.1-flash-lite`), hoặc tăng `generation.max_tokens`. **Không báo cáo số eval khi `truncated_generations > 0`** |
| `429 ... GenerateRequestsPerDayPerProjectPerModel-FreeTier` | Free tier Gemini tính quota theo ngày, theo từng model — `gemini-2.5-flash` chỉ 20 request/ngày | Đổi `LLM_MODEL` sang model khác (quota riêng), xem mức còn lại ở ai.dev/rate-limit. Eval 100 câu × 4 cấu hình cần 500+ lời gọi |
| Mọi câu đều `abstained` | τ quá cao, hoặc NLI không hiểu tiếng Việt | Chạy lại hiệu chỉnh τ (docs 06, mục 4) |
| Verify rất chậm | Chạy CPU, chưa batch | Bật cache, giảm `rerank_to`, hoặc chạy eval qua đêm |
| Tải model HF chậm mỗi lần rebuild | Cache không được mount | `.cache/` đã mount trong `docker-compose.yml`, kiểm tra quyền thư mục |
| Qdrant `connection refused` | Container chưa healthy | `docker compose ps`, đợi healthcheck |

## Quy ước làm việc

- Commit đều tay, message rõ. Lịch sử rải trong ba tuần đáng tin hơn một commit
  `initial commit` chứa toàn bộ dự án.
- Mỗi lần sửa prompt hoặc τ → chạy lại `make eval-all`, cập nhật bảng README.
- Đổi quyết định kiến trúc → thêm ADR mới, không sửa ADR cũ. ADR cũ chuyển
  trạng thái sang `Superseded by ADR-XXXX`.


## Chạy bằng model mở (Ollama)

```bash
make up-ollama
docker exec grounded-rag-ollama-1 ollama pull qwen2.5:3b-instruct-q4_K_M
LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:3b-instruct-q4_K_M make eval
```

Biến môi trường ghi đè `.env`, nên không cần sửa file để đổi provider tạm thời.

### Đo thật, 2026-09-14 — máy 7 GB RAM, CPU

Provider chạy được qua endpoint OpenAI-compatible của Ollama, không phải sửa
dòng code nào. Nhưng có hai điều phải biết trước khi dùng nó cho benchmark.

**Bộ nhớ là ràng buộc, không phải tốc độ.** Pipeline giữ đồng thời bge-m3
(~2,2 GB), bge-reranker-v2-m3 (~2,2 GB) và mDeBERTa (~1,1 GB). Cộng thêm 1,9 GB
cho qwen2.5:3b là ~7,4 GB trên máy 7 GB: lượt chạy 6 câu đã đẩy swap lên 2,3 GB.
Muốn chạy đủ 100 câu × 4 cấu hình bằng model mở thì phải bỏ bớt một model —
rẻ nhất là tắt reranker, và cái giá của việc đó đo được bằng chính eval.

**Model 3B không giữ được định dạng trích dẫn.** Với câu "thời giờ làm việc
bình thường tối đa một ngày", qwen2.5:3b trả về đúng chuỗi `[1]` ở cả 4 lần
chạy với temperature 0. Cùng prompt đó, `gemini-3.1-flash-lite` trả lời đúng —
nên đây là giới hạn của model, không phải của prompt. Nếu dùng model mở, hãy
kiểm tra định dạng trích dẫn trước khi tin bảng số.

Lượt chạy này có ích ngoài dự kiến: `[1]` là mã trích dẫn không hợp lệ, bị lớp
kiểm tra trích dẫn xoá đi, và câu trả lời thành chuỗi rỗng mà vẫn mang trạng
thái `answered`. Đó là lỗi của `apply_policy`, đã sửa — không còn mệnh đề nào
sống sót thì đó là từ chối, không phải thành công rỗng.

### Đo lại, 2026-09-19 — nút thắt là model, không phải truy xuất

Cùng câu hỏi, cùng ngữ cảnh, chỉ đổi model:

| Câu hỏi | truy xuất | qwen2.5:3b | gemini-3.1-flash-lite |
|---|---|---|---|
| "Người lao động đơn phương chấm dứt HĐLĐ không xác định thời hạn phải báo trước bao nhiêu ngày?" | Điều 35:1 hạng **1**, score 1.00 | trả lời được | trả lời được |
| "Nghỉ việc phải báo trước bao nhiêu ngày?" | Điều 35:1 hạng **3** (Điều 115 "nghỉ việc riêng" chiếm hạng 1) | **từ chối** | trả lời đủ bốn loại hợp đồng, trích đúng `[C3]` |
| "Một ngày làm việc tối đa bao nhiêu giờ?" | Điều 146:2 hạng 1 | **từ chối** | — |
| "Ai được hưởng trợ cấp hưu trí xã hội?" | Điều 21:1 BHXH hạng 1 | **từ chối** | — |
| "Đi làm muộn bị phạt bao nhiêu tiền?" | không đoạn nào vượt floor | `no_context` — **đúng**, tiền đề sai | — |

Điều đáng giá ở dòng thứ hai: Gemini đọc qua đoạn nhiễu xếp hạng nhất và tìm
thấy đáp án ở `C3`. Cùng năm đoạn đó, qwen2.5:3b từ chối. **Truy xuất không
phải nguyên nhân** của `false_abstention` — đó là giới hạn của model 3B.

Kết luận vận hành: `LLM_PROVIDER=ollama` dùng để chạy không tốn tiền và để đo,
nhưng **để demo thì dùng Gemini**:

```bash
LLM_PROVIDER=gemini LLM_MODEL=gemini-3.1-flash-lite make run
```

### Lỗi thay con số bằng mã trích dẫn (đã sửa 2026-09-19)

qwen2.5:3b trả về `"phải báo trước ít nhất [C1] ngày"` — mã trích dẫn nằm đúng
chỗ con số. 4/4 lượt sinh ở temperature 0.

Guard **không** bắt được: bỏ mã trích dẫn đi thì mệnh đề không còn con số nào,
nên luật con số không có gì để kiểm, và phần chữ còn lại vẫn entail khoản luật.
Một câu trả lời vô nghĩa được 0.99 và tới tay người dùng.

Sửa bằng prompt: quy tắc 2 nói thẳng kèm ví dụ rằng con số phải chép nguyên văn
và mã trích dẫn không bao giờ thay thế một con số. Sau khi sửa: 4/4 lượt giữ
được "45 ngày". Nếu bạn đổi model sinh, hãy kiểm lại đúng điều này trước khi
tin bảng số.


## Chỉ cần Qdrant, không cần build image API

`make up-qdrant` là đủ cho `make ingest`, `make run` và `make eval` — API chạy
native bằng `.venv`. Chỉ dùng `make up-api` khi thực sự muốn đóng gói container.

Lý do: image API cài `torch`, mà mặc định pip kéo về bản CUDA — 554 MB torch
cộng khoảng 3 GB wheel `nvidia-*` không bao giờ được nạp trên máy không GPU.
Dockerfile nay ghim bản CPU trước (`--index-url .../whl/cpu`), nhưng lần build
đầu vẫn tốn thời gian và dung lượng. Đừng chạy nó chỉ để có Qdrant.

Build hỏng giữa chừng để lại cache của buildkit; dọn bằng:

```bash
docker builder prune -f      # cache build
docker image prune -f        # image mồ côi
```
