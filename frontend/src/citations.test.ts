import { describe, expect, it } from "vitest";
import { splitCitations } from "./citations";

describe("splitCitations", () => {
  it("turns [C1] markers into citation parts", () => {
    expect(splitCitations("ít nhất 45 ngày [C1][C2].")).toEqual([
      { kind: "text", text: "ít nhất 45 ngày " },
      { kind: "cite", label: "C1" },
      { kind: "cite", label: "C2" },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves text without citations whole", () => {
    expect(splitCitations("Không tìm thấy.")).toEqual([{ kind: "text", text: "Không tìm thấy." }]);
  });

  it("does not treat a law's own brackets as citations", () => {
    expect(splitCitations("theo [Điều 35] [C1]")).toEqual([
      { kind: "text", text: "theo [Điều 35] " },
      { kind: "cite", label: "C1" },
    ]);
  });
});
