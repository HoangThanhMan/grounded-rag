// Server-sent events from a fetch() body. EventSource cannot POST, and the
// question goes in the body, so the stream is read by hand.

export interface SSEMessage {
  event: string;
  data: unknown;
}

export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const reader = body.getReader();
  // stream: true keeps a multi-byte character split across chunks intact
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const message = parse(block);
      if (message) yield message;
    }
  }
  const rest = parse(buffer + decoder.decode());
  if (rest) yield rest;
}

function parse(block: string): SSEMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  return { event, data: JSON.parse(data.join("\n")) };
}
