import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  deleteConversation,
  getConversation,
  listConversations,
  streamChat,
} from "../api";
import { applyEvent, interrupt } from "../chat";
import { Composer } from "../components/Composer";
import { Message } from "../components/Message";
import { Sidebar } from "../components/Sidebar";
import { SourcePanel } from "../components/SourcePanel";
import { today } from "../format";
import type { ChatEvent, ChatMessage, ConversationSummary } from "../types";

const EXAMPLES = [
  "Người lao động nghỉ việc phải báo trước bao nhiêu ngày?",
  "Lao động nữ sinh con được nghỉ thai sản bao lâu?",
  "Thời giờ làm thêm tối đa trong một năm là bao nhiêu giờ?",
];

export function ChatPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [asOf, setAsOf] = useState(today);
  const [selected, setSelected] = useState<{ messageId: string; label: string } | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // a conversation this page just created: its messages are already on screen
  const justCreated = useRef<string | null>(null);
  const stream = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshList = useCallback(() => {
    listConversations().then(setConversations).catch(() => {});
  }, []);

  useEffect(refreshList, [refreshList]);

  useEffect(() => {
    setSelected(null);
    setNotice(null);
    if (id && justCreated.current === id) {
      justCreated.current = null;
      return;
    }
    stream.current?.abort();
    setMessages([]);
    if (!id) return;
    let stale = false;
    getConversation(id)
      .then((c) => !stale && setMessages(c.messages))
      .catch(() => !stale && setNotice("Không mở được hội thoại này. Có thể nó đã bị xoá."));
    return () => {
      stale = true;
    };
  }, [id]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages]);

  async function send(question: string) {
    const pending = `pending-${Date.now()}`;
    // The answer's id changes on `done`. Read it when the event arrives, not
    // when React gets round to the update - by then it may have changed.
    let target = pending;

    setMessages((ms) => [
      ...ms,
      { id: `q-${pending}`, role: "user", content: question },
      { id: pending, role: "assistant", content: "", phase: "searching" },
    ]);
    setBusy(true);
    setNotice(null);
    const controller = new AbortController();
    stream.current = controller;

    const onEvent = (e: ChatEvent) => {
      if (e.event === "meta") {
        if (!id) {
          justCreated.current = e.data.conversation_id;
          navigate(`/c/${e.data.conversation_id}`, { replace: true });
        }
        refreshList();
        return;
      }
      const at = target;
      if (e.event === "done") target = e.data.message_id;
      setMessages((ms) => applyEvent({ messages: ms, target: at }, e).messages);
    };

    try {
      await streamChat(
        { question, conversation_id: id, as_of: asOf === today() ? undefined : asOf },
        onEvent,
        controller.signal,
      );
    } catch (err) {
      if (controller.signal.aborted) return;
      const text =
        err instanceof ApiError && err.status === 429
          ? `Bạn đang hỏi quá nhanh. Thử lại sau ${err.retryAfter ?? 60} giây.`
          : err instanceof ApiError
            ? err.message
            : "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
      const at = target;
      setMessages((ms) => interrupt({ messages: ms, target: at }, text).messages);
    } finally {
      if (stream.current === controller) stream.current = null;
      setBusy(false);
      refreshList();
    }
  }

  async function remove(conversationId: string) {
    try {
      await deleteConversation(conversationId);
    } catch {
      setNotice("Chưa xoá được hội thoại. Thử lại.");
      return;
    }
    if (conversationId === id) navigate("/");
    refreshList();
  }

  const selectedSource =
    selected &&
    (messages
      .find((m) => m.id === selected.messageId)
      ?.sources?.find((s) => s.label === selected.label) ??
      null);

  return (
    <div className="chat-layout">
      <Sidebar
        conversations={conversations}
        open={drawer}
        onClose={() => setDrawer(false)}
        onDelete={remove}
      />
      {drawer && <div className="backdrop" onClick={() => setDrawer(false)} />}

      <main className="conversation">
        <button type="button" className="btn drawer-toggle" onClick={() => setDrawer(true)}>
          Hội thoại
        </button>
        <div className="thread">
          {notice && <p className="notice">{notice}</p>}
          {messages.length === 0 && !id ? (
            <Welcome onAsk={send} />
          ) : (
            messages.map((m) => (
              <Message
                key={m.id}
                message={m}
                activeLabel={selected?.messageId === m.id ? selected.label : null}
                onCite={(label) => setSelected({ messageId: m.id, label })}
              />
            ))
          )}
          <div ref={bottom} />
        </div>
        <Composer busy={busy} asOf={asOf} onAsOf={setAsOf} onSend={send} />
      </main>

      {selected && <div className="backdrop backdrop-sheet" onClick={() => setSelected(null)} />}
      <SourcePanel source={selectedSource ?? null} onClose={() => setSelected(null)} />
    </div>
  );
}

function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <section className="welcome">
      <h1>Hỏi về luật lao động và bảo hiểm xã hội</h1>
      <p>
        Mỗi câu trả lời đều dẫn tới khoản luật làm căn cứ. Khi văn bản không quy định điều bạn
        hỏi, hệ thống sẽ nói là không tìm thấy thay vì đoán.
      </p>
      <div className="examples">
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="example" onClick={() => onAsk(q)}>
            {q}
          </button>
        ))}
      </div>
      <p className="welcome-note">
        Muốn đọc luật cũ? Đổi ngày ở ô bên dưới: hỏi về chế độ ốm đau vào ngày 01/01/2025 sẽ được
        trả lời theo Luật Bảo hiểm xã hội 2014.
      </p>
    </section>
  );
}
