import { splitCitations } from "../citations";

interface Props {
  text: string;
  active?: string | null;
  onCite?: (label: string) => void;
}

/** Answer text with each [C1] drawn as a tab the reader can open. */
export function CitedText({ text, active, onCite }: Props) {
  return (
    <>
      {splitCitations(text).map((part, i) =>
        part.kind === "text" ? (
          <span key={i}>{part.text}</span>
        ) : (
          <button
            key={i}
            type="button"
            className={`cite${active === part.label ? " is-active" : ""}`}
            onClick={() => onCite?.(part.label)}
            aria-label={`Mở căn cứ ${part.label}`}
          >
            {part.label.slice(1)}
          </button>
        ),
      )}
    </>
  );
}
