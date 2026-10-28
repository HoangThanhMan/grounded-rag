// How one streamed answer moves through the conversation, as a pure function
// of the events - kept out of the component so it can be tested.
//
// `target` is the id of the answer being written. It changes once, on
// `done`, from the client's placeholder to the id the server stored it under.

import type { ChatEvent, ChatMessage } from "./types";

export interface Pending {
  messages: ChatMessage[];
  target: string;
}

export const STREAM_ERRORS: Record<string, string> = {
  llm_unavailable: "Mô hình ngôn ngữ đang không phản hồi. Thử lại sau ít phút.",
  internal: "Máy chủ gặp lỗi khi trả lời câu này.",
};

export function applyEvent(state: Pending, e: ChatEvent): Pending {
  const edit = (fn: (m: ChatMessage) => ChatMessage, target = state.target): Pending => ({
    target,
    messages: state.messages.map((m) => (m.id === state.target ? fn(m) : m)),
  });
  switch (e.event) {
    case "meta":
      return state;
    case "sources":
      return edit((m) => ({ ...m, sources: e.data.sources, phase: "writing" }));
    case "token":
      return edit((m) => ({ ...m, content: m.content + e.data.text, phase: "writing" }));
    case "retry":
      // the draft failed the server's checks: a stronger model writes it again
      return edit((m) => ({ ...m, content: "", phase: "rechecking" }));
    case "done":
      return edit(
        (m) => ({
          ...m,
          id: e.data.message_id,
          content: e.data.answer,
          status: e.data.status,
          abstain_reason: e.data.abstain_reason,
          citations: e.data.citations,
          model: e.data.model,
          escalated: e.data.escalated,
          fallback: e.data.fallback,
          phase: undefined,
        }),
        e.data.message_id,
      );
    case "error":
      return edit((m) => ({
        ...m,
        phase: undefined,
        interrupted: STREAM_ERRORS[e.data.code] ?? e.data.message,
      }));
  }
}

/** The pending answer stopped before the stream could say why. */
export function interrupt(state: Pending, reason: string): Pending {
  return {
    ...state,
    messages: state.messages.map((m) =>
      m.id === state.target ? { ...m, phase: undefined, interrupted: reason } : m,
    ),
  };
}

/** The stream closed. An answer still searching or writing never got its
 * `done` or `error` - a proxy dropped it - and must not spin forever. */
export function finishStream(state: Pending): Pending {
  const open = state.messages.some((m) => m.id === state.target && m.phase !== undefined);
  return open
    ? interrupt(state, "Kết nối bị ngắt trước khi câu trả lời hoàn tất. Hỏi lại để thử lần nữa.")
    : state;
}

export interface Selection {
  messageId: string;
  label: string;
}

/** A citation clicked while the answer was still being written belongs to
 * the placeholder id; follow the answer to the id the server gave it. */
export function followAnswer(sel: Selection | null, from: string, to: string): Selection | null {
  return sel && sel.messageId === from ? { ...sel, messageId: to } : sel;
}

/** The day the law is read on: the reader's pick, else today - worked out
 * when the question is asked, so a tab left open overnight is not a day behind. */
export function askedOn(picked: string | null, today: () => string): string {
  return picked ?? today();
}
