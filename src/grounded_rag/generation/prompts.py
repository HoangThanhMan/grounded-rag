"""The contract with the model.

Everything the guard later checks is stated here first. Keep the two in
sync: if you loosen this prompt, the guard's failure rate moves.
"""

from __future__ import annotations

from grounded_rag.types import ABSTAIN_TEXT, RetrievedChunk

SYSTEM_PROMPT = f"""Bạn là trợ lý tra cứu tài liệu. Bạn CHỈ được trả lời dựa trên các đoạn tài liệu được cung cấp bên dưới.

Quy tắc bắt buộc:
1. Mỗi câu trong câu trả lời phải kết thúc bằng mã trích dẫn của đoạn tài liệu chứng minh câu đó, ví dụ: [C1] hoặc [C1][C3].
2. Mã trích dẫn LUÔN có dạng [C1], [C2], ... Không bao giờ dùng số điều luật làm mã trích dẫn: viết "[C1]", không viết "[Điều 35]".
3. Không suy diễn, không bổ sung kiến thức bên ngoài, không tổng quát hóa.
4. Nếu tài liệu không đủ thông tin để trả lời, trả lời đúng một câu duy nhất:
   "{ABSTAIN_TEXT}"
5. Trả lời ngắn gọn, tối đa 5 câu."""


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
    blocks = []
    for s in sources:
        # The label is the only thing inside brackets. It used to read
        # "[C1 (Điều 105, Khoản 1)]", which put two citable-looking tokens in
        # one pair of brackets - small models copied the article number and
        # every claim came back uncited.
        where = s.chunk.article or ""
        if where and s.chunk.clause:
            where += f", {s.chunk.clause}"
        head = f"[{s.label}]" + (f" {where}" if where else "")
        blocks.append(f"{head}\n{s.chunk.text}")
    documents = "\n\n".join(blocks)
    return f"TÀI LIỆU:\n{documents}\n\nCÂU HỎI: {question}\n\nTRẢ LỜI:"
