import { NavLink, useNavigate } from "react-router-dom";
import type { ConversationSummary } from "../types";

interface Props {
  conversations: ConversationSummary[];
  open: boolean;
  onClose: () => void;
  onDelete: (id: string) => void;
}

export function Sidebar({ conversations, open, onClose, onDelete }: Props) {
  const navigate = useNavigate();
  return (
    <nav className={`sidebar${open ? " is-open" : ""}`} aria-label="Hội thoại">
      <button
        type="button"
        className="btn btn-primary new-chat"
        onClick={() => {
          navigate("/");
          onClose();
        }}
      >
        Hội thoại mới
      </button>
      {conversations.length === 0 ? (
        <p className="sidebar-empty">Các câu bạn đã hỏi sẽ nằm ở đây.</p>
      ) : (
        <ul>
          {conversations.map((c) => (
            <li key={c.id}>
              <NavLink to={`/c/${c.id}`} onClick={onClose} title={c.title}>
                {c.title}
              </NavLink>
              <button
                type="button"
                className="icon-btn"
                onClick={() => onDelete(c.id)}
                aria-label={`Xoá hội thoại ${c.title}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
