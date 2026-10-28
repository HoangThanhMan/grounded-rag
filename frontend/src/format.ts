import type { AbstainReason, ChatMessage, Source } from "./types";

export function viDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

export function today(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** "Điều 35, khoản 1" - how a lawyer says where a clause is. */
export function where(s: Source): string {
  const clause = s.clause ? `, ${s.clause.toLowerCase()}` : "";
  return `${s.article ?? s.ref}${clause}`;
}

export const REFUSAL_WHY: Record<AbstainReason, string> = {
  retrieval_floor: "Không có điều luật nào đủ liên quan tới câu hỏi trong các văn bản đang có hiệu lực.",
  model: "Các điều luật tìm được không trả lời câu hỏi này.",
  no_citation: "Câu trả lời không dẫn được điều luật nào làm căn cứ, nên không được hiển thị.",
  truncated: "Câu trả lời dài quá giới hạn và bị cắt giữa chừng, nên không được hiển thị. Thử hỏi hẹp hơn.",
};

/** The line under an answer: which model wrote it, and why not the first one.
 * Null when no model was asked - a question refused before the LLM. */
export function answeredBy(m: Pick<ChatMessage, "model" | "escalated" | "fallback">): string | null {
  if (!m.model) return null;
  if (m.escalated) return `${m.model} · đã hỏi lại mô hình mạnh hơn (câu trả lời đầu không có căn cứ)`;
  if (m.fallback) return `${m.model} · mô hình dự phòng (mô hình chính không phản hồi)`;
  return m.model;
}
