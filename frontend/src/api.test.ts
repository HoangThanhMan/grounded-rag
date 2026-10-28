import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("the first request", () => {
  it("gets the history cookie before any other call is sent", async () => {
    const order: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        order.push(`start ${url}`);
        if (url === "/healthz") await gate;
        order.push(`end ${url}`);
        return new Response("[]", { status: 200 });
      }),
    );
    const api = await import("./api");
    const calls = Promise.all([api.listConversations(), api.listDocuments()]);
    await new Promise((r) => setTimeout(r, 10));
    expect(order).toEqual(["start /healthz"]);
    release();
    await calls;
    expect(order.slice(0, 2)).toEqual(["start /healthz", "end /healthz"]);
    expect(order.filter((o) => o.startsWith("start"))).toHaveLength(3);
  });
});
