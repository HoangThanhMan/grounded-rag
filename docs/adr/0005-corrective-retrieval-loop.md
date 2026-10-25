# ADR-0005 — Vòng truy xuất sửa lỗi tự viết, không dùng LangGraph

- **Trạng thái:** Accepted
- **Ngày:** 2026-09-11

## Bối cảnh

Phương án được cân nhắc là Agentic RAG đầy đủ: nhận diện ý định → lập kế hoạch
truy vấn → chọn công cụ → tự đánh giá kết quả truy xuất, viết lại và tìm lại
(CRAG), điều phối bằng LangGraph.

Docs 02 đã loại "agent, tool calling, reasoning nhiều bước" khỏi phạm vi. Nhưng
ngưỡng retrieval (`min_score`) để lại hai lỗi thật mà một vòng lặp giải quyết
được:

1. **Câu hỏi nói kiểu đời thường** — "nghỉ việc" thay vì "đơn phương chấm dứt
   hợp đồng lao động". Retrieval yếu → `no_context` → từ chối nhầm.
2. **Câu hỏi nhiều ý** — "báo trước bao lâu và được nghỉ phép mấy ngày". Không
   chunk nào khớp cả hai ý đủ mạnh.

Cả hai đều rơi vào `false_abstention` — cái giá của lớp phòng thủ rẻ nhất.

## Quyết định

Một vòng truy xuất sửa lỗi kiểu CRAG, **tự viết** trong
`retrieval/corrective.py`, tắt mặc định, bật ở cấu hình thứ tư
`configs/agentic.yaml`:

```
search(câu hỏi) ── điểm rerank cao nhất ≥ confident_score ──► dùng luôn
      │ yếu hơn
      ▼
planner (1 lời gọi LLM, trả JSON): còn là câu hỏi pháp luật không?
                                   các truy vấn viết lại / tách ý
      ▼
search(từng truy vấn mới) ─► gộp round-robin, bỏ trùng, áp floor
```

Nhận diện ý định được gộp vào planner (`in_domain`), nên không tốn thêm lời
gọi nào, và planner chỉ chạy khi retrieval yếu.

## Rào chắn chống vòng lặp vô tận

| Rào chắn | Ở đâu |
|---|---|
| `max_rounds` (mặc định 1, tối đa 3) — số vòng sửa lỗi | `CorrectiveConfig` |
| `max_queries` (mặc định 3) — số truy vấn mỗi vòng | `CorrectiveConfig` |
| Planner không bao giờ tiêu lời gọi cuối — câu trả lời vẫn phải được viết | `retrieve()` |
| Truy vấn đã thử (so khớp sau chuẩn hoá) không được tìm lại; hết truy vấn mới là dừng | `retrieve()` |
| `max_llm_calls` — trần cứng mỗi câu hỏi, vượt là `BudgetExceeded` | `MeteredLLM` |

Số lời gọi LLM tệ nhất = `max_rounds + 1 + max_regenerations`, biết trước khi
chạy. Có test cho trường hợp planner cứ đề xuất truy vấn mới mà không cái nào
tìm được gì (`test_the_loop_is_bounded_even_if_nothing_ever_improves`).

## Vì sao không LangGraph

Giá trị thật của LangGraph là trạng thái bền vững (checkpoint), tạm dừng chờ
người duyệt (human-in-the-loop), và đồ thị nhiều nhánh có điều kiện. Vòng này có
hai nhánh và không cần thứ nào ở trên. Thêm framework thì có thêm dependency và
một lớp trừu tượng che mất đúng phần quan trọng nhất của vòng lặp: điều kiện
dừng và ngân sách.

**Khi nào đảo quyết định:** đồ thị vượt khoảng 5 node, cần tạm dừng chờ người
duyệt, cần giữ trạng thái giữa các lượt hội thoại, hoặc có nhiều công cụ khác
loại (tra cứu văn bản, tính toán, API bên ngoài).

## Phương án bị loại

| Phương án | Vì sao loại |
|---|---|
| ReAct tự do (model tự quyết số vòng) | Không chặn trước được chi phí và độ trễ; mỗi lần chạy một quỹ đạo khác nhau, khó đánh giá |
| HyDE (sinh đoạn trả lời giả định để tìm kiếm) | Cố tình tạo nội dung bịa để dẫn retrieval. Trong dự án chống bịa, nó kéo retrieval về đúng chi tiết bịa, nhất là với câu `near_miss`. Viết lại thuật ngữ đã giải quyết vấn đề vốn từ vựng mà không phải bịa gì |
| Định tuyến sang nhiều collection theo lĩnh vực luật | Corpus hiện chỉ có 1–2 văn bản. Metadata `doc_id` đã đủ để lọc khi cần |

## Đánh đổi chấp nhận

- Thêm một lời gọi LLM và vài trăm ms cho mỗi câu có retrieval yếu. Bảng eval
  có cột `LLM calls/q` và `p95` để thấy đúng cái giá này.
- Câu ngoài phạm vi trước đây tốn 0 lời gọi LLM (floor chặn luôn), nay tốn 1:
  planner chạy trên mọi retrieval yếu, kể cả câu nó không cứu được. Đó là cái
  giá rõ nhất của cấu hình này.
- **Rủi ro riêng:** planner viết lại có thể "sửa" một câu `near_miss` thành câu
  trả lời được, làm giảm `correct_abstention`. Prompt cấm thêm chi tiết (quy tắc
  3), guard vẫn là lớp cuối, và eval báo cáo `by_type` để thấy ngay nếu chuyện
  này xảy ra.

## Đo lường

`agentic` so với `full`: `false_abstention` và `retrieval_recall`, tách theo tag
`multi_part` / `colloquial` (`by_tag`); `correct_abstention` trên `near_miss`;
chi phí `llm_calls_per_q`, `latency_p95_ms`. Nếu không cải thiện được gì, ghi
kết quả lại và để cấu hình này tắt. Quyết định này là giả thuyết cần kiểm chứng.
