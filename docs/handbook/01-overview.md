# 01 — Tổng quan

## Một câu

**grounded-rag** là một RAG API trả lời câu hỏi về luật lao động và bảo hiểm xã
hội Việt Nam; mỗi mệnh đề trong câu trả lời được một model NLI chạy tại chỗ đối
chiếu với đúng đoạn luật mà nó trích dẫn, mệnh đề không có căn cứ không tới tay
người dùng, và hệ thống từ chối khi tài liệu không đủ để trả lời.

## Bài toán

RAG thông thường (truy xuất → sinh → dừng) vẫn bịa, theo ba cách:

| Tình huống | Điều xảy ra |
|---|---|
| Truy xuất trả về đoạn không liên quan | Model vẫn cố trả lời từ đoạn sai |
| Câu hỏi không có đáp án trong tài liệu | Model trả lời bằng kiến thức của nó; người đọc tưởng đó là nội dung tài liệu |
| Câu trả lời trộn lẫn | Ba câu đúng, câu thứ tư là suy diễn; không ai nhận ra |

Trong pháp luật, một điều khoản bịa nghe hợp lý còn nguy hiểm hơn không có câu
trả lời. Và phần lớn demo RAG **không đo** chuyện này: benchmark chỉ có câu hỏi
trả lời được, nên không bao giờ biết model có biết dừng lại hay không.

## Người dùng giả định

Một người cần tra cứu quy định lao động nhưng **không đủ chuyên môn để phát hiện
câu trả lời sai** (người lao động, nhân viên HR mới). Giả định này định hình cả
thiết kế: nếu người dùng tự kiểm chứng được thì không cần guard.

## Giải pháp

Hai thứ thêm vào RAG thông thường:

1. **Groundedness guard** — tách câu trả lời thành mệnh đề, chấm từng mệnh đề
   với đoạn nó trích bằng NLI (`P(entailment)`), kèm các luật rẻ (luật con số,
   kiểm tra mã trích dẫn). Mệnh đề không đạt bị bỏ hoặc buộc sinh lại. Chi tiết:
   [07](07-guard.md).
2. **Bộ đo lường** — 100 câu hỏi gán nhãn tay, 37 câu cố tình không có đáp án
   (ba loại bẫy); bốn cấu hình chạy trên cùng dữ liệu và chấm bằng cùng một thước
   đo. Chi tiết: [08](08-evaluation.md).

Quanh đó là bốn **lớp phòng thủ**, chạy theo thứ tự rẻ trước:

| Lớp | Cơ chế | Chi phí | Chặn gì |
|---|---|---|---|
| 1 | Ngưỡng retrieval (`min_score`) | ~0, chưa gọi LLM | Câu hỏi ngoài phạm vi |
| 2 | Prompt cho phép model tự từ chối bằng một câu cố định | nằm trong lời gọi sinh | Model tự thấy tài liệu không đủ |
| 3 | Kiểm tra mã trích dẫn | ~0 | Model trích `[C9]` không tồn tại |
| 4 | NLI guard + luật con số | 1 forward/mệnh đề | Mệnh đề tài liệu không nói |

## Corpus

| Văn bản | Số hiệu | Hiệu lực | Chunk structural |
|---|---|---|---|
| Bộ luật Lao động 2019 | 45/2019/QH14 | 01/01/2021 | 684 |
| Luật Bảo hiểm xã hội 2024 | 41/2024/QH15 | 01/07/2025 | 557 |

Lấy từ Công báo (bản gốc khi ban hành, chưa hợp nhất các lần sửa đổi), đã commit
trong `data/corpus/`. Chi tiết: [06](06-ingest-and-retrieval.md).

## Kết quả đo được (2026-10-12)

Generator `gemini-3.1-flash-lite` (temperature 0), 80 câu `test` (50 trả lời
được, 30 không), thước đo NLI ở τ 0.5. Số trong `reports/2026-10-12-gemini/`.

| Cấu hình | Halluc. ↓ | Correct abst. ↑ | False abst. ↓ | Retr. recall ↑ | LLM calls/q | p95 |
|---|---|---|---|---|---|---|
| `baseline` | 0.088 | 0.93 | 0.02 | 0.97 | 1.00 | 40 s |
| `threshold` | 0.075 | 0.97 | 0.06 | 0.89 | 0.76 | 34 s |
| `full` | 0.000\* | 0.93 | 0.08 | 0.93 | 0.86 | 69 s |
| `agentic` | 0.000\* | 0.93 | 0.08 | 0.95 | 1.26 | 71 s |

Đọc đúng bảng này:

- **\* Số 0 của guard không phải phép đo độc lập**: thước đo là chính model của
  guard, ở chính ngưỡng của guard. Đọc tay cho thấy ít nhất 3/7 câu baseline bị
  chấm "bịa" thực ra đúng nguyên văn luật ([08](08-evaluation.md) mục "Điểm yếu").
- **Retrieval floor là lợi ích rẻ nhất**: chặn 17/30 câu không có đáp án trước
  khi gọi LLM.
- **Vòng corrective không đáng tiền trên lượt chạy này**: thêm 0.4 lời gọi LLM
  mỗi câu, không cứu được câu nào.
- **Độ trễ là do CPU laptop**: rerank 8–11 s, mỗi lời gọi Gemini free tier ~12 s.

Phát hiện quan trọng nhất ([07](07-guard.md)): trên 23 mệnh đề dev gán nhãn tay,
**không có ngưỡng τ nào tách được mệnh đề đúng khỏi mệnh đề sai** — cả 6 mệnh đề
sai đều được ≥ 0.70.

## Trạng thái

| Hạng mục | Trạng thái |
|---|---|
| Pipeline đầu-cuối với model thật | Chạy được |
| 135 test, lint, CI trên Python 3.12 và 3.14 | Xanh |
| Benchmark 4 cấu hình × 80 câu với Gemini | Có, trong README |
| Chấm tay 30 câu, RAGAS với giám khảo thật | **Chưa làm** |
| Demo public, database, job nền, auth cho `/chat` | **Chưa có** — kế hoạch ở [../12](../12-assessment-and-plan.md), [../13](../13-sprint-plan.md) |

## Bối cảnh

Dự án portfolio cá nhân, một người, ~3h/ngày, lõi làm trong 3 tuần (09–10/2026).
Nhắm vị trí AI Engineer intern/fresher và Backend fresher. Nối tiếp luận văn về
phát hiện hallucination trong dịch máy.

## Cố tình không làm

Multi-tenant, quản lý người dùng, Kubernetes, agent tự do / framework điều phối
(LangChain, LangGraph), fine-tune model sinh, định dạng ngoài PDF/Markdown. Lý do
từng mục: [../02-requirements.md](../02-requirements.md) và các ADR.

---

[← Handbook](README.md) · [02 — Tech stack →](02-tech-stack.md)
