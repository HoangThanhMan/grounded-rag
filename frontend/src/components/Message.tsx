import { useState } from "react";
import { sendFeedback } from "../api";
import { REFUSAL_WHY, answeredBy } from "../format";
import type { ChatMessage, Rating } from "../types";
import { CitedText } from "./Citation";

interface Props {
  message: ChatMessage;
  activeLabel: string | null;
  onCite: (label: string) => void;
}

export function Message({ message, activeLabel, onCite }: Props) {
  if (message.role === "user") {
    return <div className="msg msg-user">{message.content}</div>;
  }
  if (message.phase === "searching") {
    return <div className="msg msg-answer is-pending">Đang tìm điều luật liên quan…</div>;
  }
  if (message.phase === "rechecking") {
    return (
      <div className="msg msg-answer is-pending">
        Câu trả lời chưa dẫn được căn cứ, đang hỏi lại mô hình mạnh hơn…
      </div>
    );
  }

  const refused = message.status && message.status !== "answered";
  return (
    <article className="msg msg-answer" aria-busy={message.phase === "writing"}>
      {refused ? (
        <div className="refusal">
          <p className="refusal-title">Không tìm thấy căn cứ trong văn bản đang có hiệu lực</p>
          {message.abstain_reason && <p>{REFUSAL_WHY[message.abstain_reason]}</p>}
        </div>
      ) : (
        <p className="answer-text">
          <CitedText text={message.content} active={activeLabel} onCite={onCite} />
          {message.phase === "writing" && <span className="caret" aria-hidden />}
        </p>
      )}
      {message.interrupted && <p className="interrupted">{message.interrupted}</p>}
      {!message.phase && !message.interrupted && message.status === "answered" && (
        <Feedback messageId={message.id} initial={message.feedback ?? null} />
      )}
      {!message.phase && answeredBy(message) && (
        <p className="answered-by">{answeredBy(message)}</p>
      )}
    </article>
  );
}

function Feedback({ messageId, initial }: { messageId: string; initial: Rating | null }) {
  const [rating, setRating] = useState<Rating | null>(initial);
  const [failed, setFailed] = useState(false);

  async function rate(r: Rating) {
    const before = rating;
    setRating(r);
    setFailed(false);
    try {
      await sendFeedback(messageId, r);
    } catch {
      setRating(before);
      setFailed(true);
    }
  }

  return (
    <div className="feedback" role="group" aria-label="Đánh giá câu trả lời">
      <button type="button" aria-pressed={rating === "up"} onClick={() => rate("up")} title="Hữu ích">
        👍
      </button>
      <button type="button" aria-pressed={rating === "down"} onClick={() => rate("down")} title="Sai hoặc không hữu ích">
        👎
      </button>
      {failed && <span className="feedback-error">Chưa gửi được, thử lại.</span>}
    </div>
  );
}
