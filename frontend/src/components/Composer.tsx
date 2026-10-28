import { useState, type FormEvent, type KeyboardEvent } from "react";

const MAX = 1000;

interface Props {
  busy: boolean;
  asOf: string;
  onAsOf: (day: string) => void;
  onSend: (question: string) => void;
}

export function Composer({ busy, asOf, onAsOf, onSend }: Props) {
  const [text, setText] = useState("");

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, MAX))}
        onKeyDown={onKey}
        rows={2}
        placeholder="Hỏi về Bộ luật Lao động, Luật Bảo hiểm xã hội…"
        aria-label="Câu hỏi"
      />
      <div className="composer-bar">
        <label className="as-of">
          Đọc luật vào ngày
          <input type="date" value={asOf} onChange={(e) => e.target.value && onAsOf(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
          {busy ? "Đang trả lời…" : "Hỏi"}
        </button>
      </div>
      <p className="disclaimer">Công cụ tra cứu, không phải tư vấn pháp lý. Luôn đối chiếu với văn bản gốc.</p>
    </form>
  );
}
