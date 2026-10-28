import { describe, expect, it } from "vitest";
import { readSSE } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>) {
  const out = [];
  for await (const e of readSSE(body)) out.push(e);
  return out;
}

describe("readSSE", () => {
  it("reassembles events cut in the middle of a data line", async () => {
    const events = await collect(
      streamOf(
        'event: token\ndata: {"te',
        'xt":"Xin "}\n\nevent: done\nda',
        'ta: {"status":"answered"}\n\n',
      ),
    );
    expect(events).toEqual([
      { event: "token", data: { text: "Xin " } },
      { event: "done", data: { status: "answered" } },
    ]);
  });

  it("splits a multi-byte character across chunks without mangling it", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"Điều"}\n\n');
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, 22));
        c.enqueue(bytes.slice(22));
        c.close();
      },
    });
    expect(await collect(body)).toEqual([{ event: "token", data: { text: "Điều" } }]);
  });
});
