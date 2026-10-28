import { readSSE } from "./sse";
import type {
  ChatEvent,
  Conversation,
  ConversationSummary,
  LibraryDocument,
  Rating,
} from "./types";

/** An error response, read from the API's one error shape. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter?: number,
  ) {
    super(message);
  }
}

async function fail(r: Response): Promise<never> {
  let code = `http_${r.status}`;
  let message = r.statusText || "Yêu cầu không thành công";
  try {
    const body = await r.json();
    code = body.error?.code ?? code;
    message = body.error?.message ?? message;
  } catch {
    // not JSON - a proxy error page; keep the status line
  }
  const retry = Number(r.headers.get("retry-after"));
  throw new ApiError(r.status, code, message, Number.isFinite(retry) && retry > 0 ? retry : undefined);
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) await fail(r);
  return r.json() as Promise<T>;
}

async function empty(path: string, init?: RequestInit): Promise<void> {
  const r = await fetch(path, init);
  if (!r.ok) await fail(r);
}

export interface ChatRequest {
  question: string;
  conversation_id?: string;
  as_of?: string;
}

export async function streamChat(
  req: ChatRequest,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!r.ok || !r.body) await fail(r);
  for await (const message of readSSE(r.body!)) onEvent(message as ChatEvent);
}

export const listConversations = () => json<ConversationSummary[]>("/api/conversations");

export const getConversation = (id: string) => json<Conversation>(`/api/conversations/${id}`);

export const deleteConversation = (id: string) =>
  empty(`/api/conversations/${id}`, { method: "DELETE" });

export const sendFeedback = (messageId: string, rating: Rating) =>
  json(`/api/messages/${messageId}/feedback`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ rating }),
  });

export const listDocuments = () => json<LibraryDocument[]>("/api/documents");

export const uploadDocument = (form: FormData, adminKey: string) =>
  json<LibraryDocument>("/api/documents", {
    method: "POST",
    headers: { "X-API-Key": adminKey },
    body: form,
  });

export const deleteDocument = (id: string, adminKey: string) =>
  empty(`/api/documents/${id}`, { method: "DELETE", headers: { "X-API-Key": adminKey } });
