import { describe, expect, it } from "vitest";
import { applyEvent, askedOn, finishStream, followAnswer, type Pending } from "./chat";
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
          model: "gemini-3.5-flash", escalated: true, fallback: false,
        },
      },
    ]);
    expect(ms[1]).toMatchObject({
      id: "m1", content: "Không quá 200 giờ [C1].", status: "answered", phase: undefined,
      sources: [source], model: "gemini-3.5-flash", escalated: true, fallback: false,
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

  it("drops the failed draft when a stronger model starts over", () => {
    const ms = run([
      { event: "token", data: { text: "Không quá 200 giờ." } },
      { event: "retry", data: { reason: "no_citation" } },
    ]);
    expect(ms[1]).toMatchObject({ content: "", phase: "rechecking" });
    const after = run([
      { event: "token", data: { text: "Không quá 200 giờ." } },
      { event: "retry", data: { reason: "no_citation" } },
      { event: "token", data: { text: "Không quá 200 giờ [C1]." } },
    ]);
    expect(after[1]).toMatchObject({ content: "Không quá 200 giờ [C1].", phase: "writing" });
  });

  it("leaves the user's question untouched", () => {
    expect(run([{ event: "token", data: { text: "x" } }])[0]).toBe(start[0]);
  });
});

describe("finishStream", () => {
  it("marks an answer the stream never settled as interrupted", () => {
    let state: Pending = { messages: start, target: "pending" };
    state = applyEvent(state, { event: "token", data: { text: "Không quá " } });
    const done = finishStream(state);
    expect(done.messages[1]).toMatchObject({
      phase: undefined,
      interrupted: "Kết nối bị ngắt trước khi câu trả lời hoàn tất. Hỏi lại để thử lần nữa.",
    });
  });

  it("leaves a finished answer alone", () => {
    let state: Pending = { messages: start, target: "pending" };
    state = applyEvent(state, {
      event: "done",
      data: { message_id: "m1", answer: "A [C1].", status: "answered", abstain_reason: null,
              citations: ["C1"], latency_ms: 1, model: "m", escalated: false, fallback: false },
    });
    expect(finishStream(state)).toEqual(state);
  });
});

describe("followAnswer", () => {
  it("keeps a citation opened during streaming open once the answer gets its id", () => {
    const sel = { messageId: "pending", label: "C2" };
    expect(followAnswer(sel, "pending", "m1")).toEqual({ messageId: "m1", label: "C2" });
    expect(followAnswer(sel, "other", "m1")).toBe(sel);
    expect(followAnswer(null, "pending", "m1")).toBeNull();
  });
});

describe("askedOn", () => {
  it("reads the law today unless the reader picked a day", () => {
    expect(askedOn(null, () => "2026-10-29")).toBe("2026-10-29");
    expect(askedOn("2025-01-01", () => "2026-10-29")).toBe("2025-01-01");
  });
});
