# 09 — Runbook

## Cài đặt

```bash
cd ~/Data/project/grounded-rag
python -m venv .venv && source .venv/bin/activate

make install        # chỉ runtime, đủ để chạy test và mock pipeline
make dev-install    # thêm torch/transformers/ragas/streamlit - nặng, vài GB

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
make run
make demo                                # streamlit :8501
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
| Lỗi khởi động `llm_provider ... Input should be` | Tên provider sai chính tả — cố tình không rơi về mock | Sửa `LLM_PROVIDER` trong `.env` |
| API trả `503` | Provider LLM không phản hồi sau khi đã thử lại | Kiểm tra key, `*_BASE_URL`, Ollama/vLLM có đang chạy không |
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
