"""The contract with the model.

Everything the guard later checks is stated here first. Keep the two in
sync: if you loosen this prompt, the guard's failure rate moves.
"""

from __future__ import annotations

from grounded_rag.types import ABSTAIN_TEXT, RetrievedChunk

SYSTEM_PROMPT = f"""Bạn là trợ lý tra cứu tài liệu. Bạn CHỈ được trả lời dựa trên các đoạn tài liệu được cung cấp bên dưới.

Quy tắc bắt buộc:
1. Nếu tài liệu có thông tin trả lời được câu hỏi thì BẮT BUỘC phải trả lời. Chỉ từ chối khi không đoạn nào nhắc tới điều được hỏi.
2. Chép đúng nguyên văn con số, thời hạn và điều kiện từ tài liệu. KHÔNG BAO GIỜ thay một con số bằng mã trích dẫn: viết "ít nhất 45 ngày [C1]", không viết "ít nhất [C1] ngày".
3. Mã trích dẫn đặt ở CUỐI mỗi câu, dạng [C1], [C2] hoặc [C1][C3]. Không dùng số điều luật làm mã trích dẫn: viết "[C1]", không viết "[Điều 35]".
4. Không suy diễn, không bổ sung kiến thức bên ngoài, không tổng quát hóa.
5. Nếu không đoạn nào trả lời được câu hỏi, viết đúng một câu duy nhất và không thêm bất cứ thứ gì khác:
   "{ABSTAIN_TEXT}"
6. Trả lời ngắn gọn, tối đa 5 câu."""


ANSWER_REMINDER = "Trả lời bằng câu văn đầy đủ, cuối mỗi câu ghi mã [C1], [C2]..."


_PLANNER_PROMPT = """Bạn là bộ lập kế hoạch truy vấn cho hệ thống tra cứu văn bản pháp luật Việt Nam. Bạn KHÔNG trả lời câu hỏi.

Lần tìm kiếm với câu hỏi gốc chưa tìm được đoạn tài liệu đủ liên quan. Hãy viết lại thành truy vấn tìm kiếm tốt hơn:
1. Dùng thuật ngữ pháp lý thay cho cách nói thông thường, ví dụ "nghỉ việc" → "đơn phương chấm dứt hợp đồng lao động".
2. Nếu câu hỏi gồm nhiều ý độc lập, tách mỗi ý thành một truy vấn riêng, tối đa {max_queries} truy vấn.
3. Không thêm con số, điều khoản hay chi tiết mà câu hỏi không nhắc tới.
4. Nếu đó không phải câu hỏi về pháp luật (chào hỏi, chủ đề khác hẳn), đặt "in_domain": false.

Chỉ trả về đúng một đối tượng JSON, không giải thích:
{{"in_domain": true, "queries": ["truy vấn 1", "truy vấn 2"]}}"""


def planner_system_prompt(max_queries: int) -> str:
    """Rule 3 matters most: a rewrite that invents a detail would steer
    retrieval towards it - a hallucination planted before generation even starts."""
    return _PLANNER_PROMPT.format(max_queries=max_queries)


def build_planner_prompt(question: str, tried: list[str]) -> str:
    prompt = f"CÂU HỎI: {question}"
    earlier = [q for q in tried if q != question]
    if earlier:
        listed = "\n".join(f"- {q}" for q in earlier)
        prompt += f"\n\nCÁC TRUY VẤN ĐÃ THỬ, KHÔNG HIỆU QUẢ (đừng lặp lại):\n{listed}"
    return prompt


def build_user_prompt(question: str, sources: list[RetrievedChunk]) -> str:
    # The label is the only thing in the header. "[C1] Điều 105, Khoản 1" was
    # copied by small models as "[Điều 105][C1]", an answer with no sentence
    # in it; the chunk text already opens with its article heading.
    documents = "\n\n".join(f"[{s.label}]\n{s.chunk.text}" for s in sources)
    # Restated right before the answer slot: qwen2.5:3b followed the system
    # prompt's citation rule in 1 of 4 answers, and in 3 of 4 with this line.
    return (
        f"TÀI LIỆU:\n{documents}\n\nCÂU HỎI: {question}\n\n"
        f"{ANSWER_REMINDER}\n\nTRẢ LỜI:"
    )
