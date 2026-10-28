import { viDate, where } from "../format";
import type { Source } from "../types";

interface Props {
  source: Source | null;
  onClose: () => void;
}

/** The cited clause, set like a page of the gazette it came from. */
export function SourcePanel({ source, onClose }: Props) {
  if (!source) {
    return (
      <aside className="source source-empty" aria-label="Căn cứ pháp lý">
        <p>Bấm vào số trích dẫn trong câu trả lời để đọc nguyên văn điều luật.</p>
      </aside>
    );
  }
  const [heading, ...body] = source.text.split("\n");
  return (
    <aside className="source is-open" aria-label="Căn cứ pháp lý">
      <header className="source-head">
        <span className="source-tab">{source.label.slice(1)}</span>
        <div>
          <h2>{where(source)}</h2>
          <p className="source-doc">{source.doc_title ?? source.doc_id}</p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Đóng">
          ×
        </button>
      </header>
      <div className="source-page">
        <p className="source-heading">{heading}</p>
        {body.map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>
      <p className="source-validity">
        {source.effective_date ? `Hiệu lực từ ${viDate(source.effective_date)}` : "Chưa rõ ngày hiệu lực"}
        {source.expiry_date ? `, hết hiệu lực ${viDate(source.expiry_date)}` : ""}
      </p>
    </aside>
  );
}
