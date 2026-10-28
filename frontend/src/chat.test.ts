import { describe, expect, it } from "vitest";
import { applyEvent, type Pending } from "./chat";
import type { ChatEvent, ChatMessage } from "./types";

const start: ChatMessage[] = [
  { id: "q", role: "user", content: "Làm thêm tối đa bao nhiêu giờ?" },
  { id: "pending", role: "assistant", content: "", phase: "searching" },
];

function run(events: ChatEvent[]): ChatMessage[] {
  let state: Pending = { messages: start, target: "pending" };
  for (const e of events) state = applyEvent(state, e);
  return state.messages;
}

const source = {
  label: "C1", score: 0.9, ref: "blld:Điều 107:3", doc_id: "blld", doc_title: "BLLĐ",
  article: "Điều 107", clause: "Khoản 3", text: "Điều 107\n3. ...", effective_date: "2021-01-01",
  expiry_date: null,
};

describe("applyEvent", () => {
  it("streams into the pending answer and settles it on done", () => {
    const ms = run([
      { event: "sources", data: { standalone_question: "q", sources: [source] } },
      { event: "token", data: { text: "Không quá " } },
      { event: "token", data: { text: "200 giờ [C1]" } },
      {
        event: "done",
        data: {
          message_id: "m1", answer: "Không quá 200 giờ [C1].", status: "answered",
          abstain_reason: null, citations: ["C1"], latency_ms: 10,
        },
      },
    ]);
    expect(ms[1]).toMatchObject({
      id: "m1", content: "Không quá 200 giờ [C1].", status: "answered", phase: undefined,
      sources: [source],
    });
  });

  it("keeps the streamed text and marks it interrupted on error", () => {
    const ms = run([
      { event: "token", data: { text: "Không quá " } },
      { event: "error", data: { code: "llm_unavailable", message: "down" } },
    ]);
    expect(ms[1]).toMatchObject({
      content: "Không quá ",
      phase: undefined,
      interrupted: "Mô hình ngôn ngữ đang không phản hồi. Thử lại sau ít phút.",
    });
  });

  it("leaves the user's question untouched", () => {
    expect(run([{ event: "token", data: { text: "x" } }])[0]).toBe(start[0]);
  });
});
