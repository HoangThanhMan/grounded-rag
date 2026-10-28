// "45 ngày [C1][C2]." -> text and citation parts, so a citation can render
// as something the reader clicks. Only the [C<n>] labels the prompt asks
// for count; "[Điều 35]" stays text.

export type Part = { kind: "text"; text: string } | { kind: "cite"; label: string };

const CITATION = /\[(C\d+)\]/g;

export function splitCitations(text: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(CITATION)) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: text.slice(last, at) });
    parts.push({ kind: "cite", label: m[1] });
    last = at + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}
