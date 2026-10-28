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
    case "done":
      return edit(
        (m) => ({
          ...m,
          id: e.data.message_id,
          content: e.data.answer,
          status: e.data.status,
          abstain_reason: e.data.abstain_reason,
          citations: e.data.citations,
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
