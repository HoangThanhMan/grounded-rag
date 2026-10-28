import { describe, expect, it } from "vitest";
import { answeredBy } from "./format";

describe("answeredBy", () => {
  it("names the model, and why it was not the first one", () => {
    expect(answeredBy({ model: "gemini-3.1-flash-lite", escalated: false, fallback: false }))
      .toBe("gemini-3.1-flash-lite");
    expect(answeredBy({ model: "gemini-3.5-flash", escalated: true, fallback: false }))
      .toBe("gemini-3.5-flash · đã hỏi lại mô hình mạnh hơn (câu trả lời đầu không có căn cứ)");
    expect(answeredBy({ model: "gemini-3.5-flash-lite", escalated: false, fallback: true }))
      .toBe("gemini-3.5-flash-lite · mô hình dự phòng (mô hình chính không phản hồi)");
  });

  it("says nothing when no model wrote the answer", () => {
    // refused before any model was asked, or saved before models were recorded
    expect(answeredBy({ model: null })).toBeNull();
    expect(answeredBy({})).toBeNull();
  });
});
