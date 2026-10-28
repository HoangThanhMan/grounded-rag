// The API's shapes, as backend/src/grounded_rag/api/schemas.py defines them.

export type AnswerStatus = "answered" | "abstained" | "no_context";
export type AbstainReason = "retrieval_floor" | "model" | "no_citation";
export type Rating = "up" | "down";

export interface Source {
  label: string;
  score: number;
  ref: string;
  doc_id: string;
  doc_title: string | null;
  article: string | null;
  clause: string | null;
  text: string;
  effective_date: string | null;
  expiry_date: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: AnswerStatus | null;
  abstain_reason?: AbstainReason | null;
  sources?: Source[] | null;
  citations?: string[] | null;
  feedback?: Rating | null;
  // only while an answer is on its way
  phase?: "searching" | "writing";
  interrupted?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
}

export interface LibraryDocument {
  id: string;
  title: string;
  number: string | null;
  issued_by: string | null;
  effective_date: string | null;
  expiry_date: string | null;
  filename: string;
  status: "processing" | "ready" | "failed";
  chunks: number;
  error: string | null;
  updated_at: string;
}

export interface DoneData {
  message_id: string;
  answer: string;
  status: AnswerStatus;
  abstain_reason: AbstainReason | null;
  citations: string[];
  latency_ms: number;
}

export type ChatEvent =
  | { event: "meta"; data: { conversation_id: string; title: string } }
  | { event: "sources"; data: { standalone_question: string; sources: Source[] } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: DoneData }
  | { event: "error"; data: { code: string; message: string } };
