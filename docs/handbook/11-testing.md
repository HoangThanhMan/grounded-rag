# 11 — Kiểm thử

## Chiến lược

- **Mọi test chạy trên provider `mock`**, bất kể `.env` nói gì:
  `tests/conftest.py` đặt `LLM_PROVIDER=mock` và `QDRANT_URL=:memory:` **trước**
  khi bất cứ thứ gì import `grounded_rag.config` (settings đọc môi trường một lần
  lúc import). Không key, không tải model, không mạng.
- **Test nói bằng hành vi**: tên test là một câu đặc tả
  (`test_a_refusal_is_200_but_a_provider_outage_is_503`). Đọc danh sách tên là
  đọc yêu cầu của hệ thống.
- **Mỗi lỗi thật đã gặp có một test** — "lao động1.", "[60 ngày]", trích dẫn sau
  dấu chấm, "[C1]" trơ trọi, model thinking bị cắt…
- **Code production thật khi có thể**: Qdrant chạy chế độ nhúng `:memory:` (đúng
  `QdrantStore`, không phải mock); LLM client chạy qua `httpx.MockTransport` để
  kiểm request/response thật; API qua `TestClient` / `httpx.ASGITransport`.
- **Thay thành phần bằng `monkeypatch`**: `service.get_llm_client`,
  `corrective.get_reranker` được thay bằng lớp giả có kịch bản (`Scripted`,
  `Refuses`, `CutOff`, `SlowReranker`).

## Chạy

```bash
make test                                   # = python -m pytest -q  (135 test, ~7 s)
pytest tests/test_policy.py -q              # một file
pytest -k "abstention" -q                   # theo từ khóa trong tên
pytest tests/test_service_smoke.py -k agentic -s   # xem print, đặt breakpoint
make lint                                   # ruff check src eval tests app scripts
```

`pyproject.toml`: `pythonpath = ["src", "."]` (import được cả `grounded_rag` lẫn
`eval`), `testpaths = ["tests"]`. Test async dùng `@pytest.mark.asyncio`.

## Từng file test

| File | Số test | Kiểm tra gì |
|---|---|---|
| `test_api.py` | 11 | `/healthz`; config lạ → 404; config là tên không phải đường dẫn; từ chối = 200, provider chết = 503; `/configs` liệt kê đủ YAML kèm τ; UI được phục vụ từ API; `/ingest` tắt khi chưa có key (403), sai key (401), chỉ đọc dưới `DATA_ROOT` (400), không xóa được index qua HTTP, đúng key thì index được |
| `test_chunkers.py` | 12 | Cắt theo khoản; mọi khoản mang tiêu đề Điều; `ref` đúng định dạng gold; Chương là metadata; dòng bị ngắt nhắc "Điều 35" không phải Điều mới; mảnh khoản dài giữ tiêu đề và câu dẫn danh sách; metadata đóng lên mọi chunk; id theo nội dung; fallback khi không có cấu trúc; recursive đúng ngân sách và overlap không dính chữ |
| `test_citation.py` | 5 | Trích theo thứ tự, không trùng; gỡ mã; mã không tồn tại bị đánh dấu; chỉ nhãn nằm trong ngoặc |
| `test_claim_splitter.py` | 11 | Tách câu giữ trích dẫn; "Điều 35." và "khoản 1." không kết thúc câu; trích dẫn sau dấu chấm; mục danh sách; "[60 ngày]" được bỏ ngoặc; "[Điều 105]" bị bỏ; "Câu trả lời:" bị bỏ; câu có trích dẫn kết thúc bằng ":" vẫn là mệnh đề; đầu ra của guard tách lại ra đúng mệnh đề |
| `test_compute.py` | 2 | Pool chạy lời gọi của request cũ trước; lỗi trong lời gọi model tới đúng request |
| `test_concurrency.py` | 1 | `/healthz` trả lời ngay khi ba `/chat` đang chờ reranker chậm 0,4 s |
| `test_corrective.py` | 12 | Đọc JSON planner lẫn trong văn xuôi; plan hỏng → không truy vấn mới; cắt ở `max_queries`; `merge` chia chỗ cho mọi truy vấn con, bỏ trùng, giữ điểm cao, áp floor; truy xuất tự tin không tốn lời gọi; vòng lặp có trần; planner lặp lại câu hỏi thì dừng; không tiêu lời gọi dành cho câu trả lời; out-of-domain dừng trước khi sinh; vòng tắt thì không lập kế hoạch |
| `test_eval_run.py` | 2 | Một câu lỗi không làm mất cả lượt chạy; lượt khỏe không có `errored` |
| `test_instrument.py` | 4 | Cửa sổ recursive được chấm qua các khoản nó chứa; câu trải hai khoản liền kề được chứng minh; chunk structural chấm đúng như được trích; câu từ chối không có gì để chấm |
| `test_lexical.py` | 5 | Bigram âm tiết; số bỏ số 0 đầu; BM25 xếp đúng khoản lên đầu; sparse chỉ trả chunk có chung term; văn bản hết hiệu lực không bao giờ được truy xuất |
| `test_llm_client.py` | 15 | Request/response OpenAI-compatible và Anthropic; câu bị cắt được đánh dấu; `reasoning_effort` chỉ gửi khi cấu hình; thử lại lỗi tạm thời; 429 chờ đúng thời gian server yêu cầu; lỗi 4xx thất bại ngay; lỗi kết nối → `LLMUnavailable`; chi phí từ đơn giá token; stream; ngân sách là trần cứng; sai tên provider là lỗi khởi động; temperature với Anthropic; dùng chung connection pool |
| `test_loaders.py` | 3 | Front matter thành metadata; không có front matter thì giữ nguyên; sample corpus có metadata |
| `test_metrics.py` | 8 | Cửa sổ chứa khoản gold là trúng; chunk structural khớp theo `ref`; khoản khác không tính; đoạn boilerplate chung không phải "chứa"; nửa khoản dài vẫn tính; trích dẫn trong mệnh đề bị guard bỏ không tính; hallucination đọc từ verdict của thước đo, không phải của pipeline; các lớp phòng thủ cộng lại bằng `correct_abstention` |
| `test_nli_verifier.py` | 8 | Chuẩn hóa số; số không có trong premise → không được chứng minh; view theo mục giữ tiêu đề và câu dẫn; mỗi câu là một view; premise một dòng; lấy view tốt nhất và zero số bịa; quy tắc và ngoại lệ nối bằng ";" là hai view; cache có giới hạn, giữ cái mới dùng |
| `test_policy.py` | 15 | Mệnh đề đạt đi qua; không đạt bị bỏ; không trích dẫn không bao giờ đạt; `partial`; sinh lại một lần rồi dừng; guard tắt không sinh lại, không bỏ gì, giữ nguyên văn; nhận ra câu từ chối; không còn mệnh đề → từ chối chứ không trả rỗng; sinh ra 0 mệnh đề thì thử lại; câu đạt hết không sinh lại; trích nhầm nguồn được sửa nhãn, không cứu được câu không nguồn nào chứng minh; trích 3 nguồn được chấm từng cặp |
| `test_qdrant_store.py` | 5 | Upsert idempotent; sparse tìm đúng khoản; payload khứ hồi ra đúng `Chunk`; lọc hiệu lực chạy trong Qdrant; `reset` xóa index |
| `test_service_smoke.py` | 8 | Đầu-cuối trên mock: trả lời có trích dẫn đã kiểm chứng; câu ngoài phạm vi không tới LLM; model tự từ chối là `abstained (model)`, 1 lời gọi; câu bị cắt hiện trong trace; baseline báo cáo mệnh đề không kiểm chứng; `agentic` tách câu hai ý và lấy đủ Điều 35:1 + Điều 113:1; bỏ cuộc khi sinh lại vẫn giữ mệnh đề đã kiểm chứng; từ chối sau sinh lại vẫn hiện mệnh đề guard đã loại |
| `test_tracing.py` | 3 | Một câu trả lời thành một trace Langfuse (client giả); export lỗi không làm hỏng câu trả lời; thời điểm bắt đầu span không lọt vào response API |

## Không được test

- Model thật (bge-m3, reranker, mDeBERTa) — chỉ kiểm bằng `scripts/nli_probe.py`
  và các lượt eval thật.
- Provider thật — chỉ `MockTransport`.
- Langfuse server thật, Prometheus scrape thật.
- Web UI (`app/web/`) — không có test frontend.
- `scripts/` — không có test (trừ phần dùng chung với `eval/`).
- Docker image — CI không build.

## Viết test mới

Mẫu thường dùng:

```python
import pytest
from grounded_rag import service
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import LLMResponse
from grounded_rag.service import answer_question

class Scripted:                              # LLM trả lần lượt từng chuỗi
    def __init__(self, *texts): self.texts = list(texts)
    async def complete(self, system, user, **kw):
        return LLMResponse(text=self.texts.pop(0), tokens=5)

@pytest.mark.asyncio
async def test_something(monkeypatch):
    monkeypatch.setattr(service, "get_llm_client", lambda: Scripted("... [C1]."))
    answer = await answer_question("…", RunConfig.from_yaml("configs/full.yaml"))
    assert answer.status == "answered"
```

Chú ý:

- Store mock là singleton theo chunker trong tiến trình test; xem
  `tests/test_service_smoke.py` để biết cách nó ingest `data/sample_corpus` trước.
- Factory dùng `lru_cache`; nếu test đổi settings, phải `cache_clear()` factory
  tương ứng hoặc `monkeypatch` thẳng hàm `get_*` ở **nơi nó được dùng**
  (`service.get_llm_client`, không phải `llm_client.get_llm_client`).
- Đổi một setting trong test: `monkeypatch.setattr(settings, "admin_api_key", "dev")`
  (mẫu trong `tests/test_api.py`) — phần lớn code đọc `settings` lúc gọi, không
  phải lúc import. Ngoại lệ là các factory đã cache.
- Đặt tên test bằng một câu mô tả hành vi.

---

[← 10 — Cấu hình & vận hành](10-configuration-and-operations.md) · [Handbook](README.md) · [12 — Thuật ngữ →](12-glossary.md)
