import { getToken } from "./auth";

// Inlined at build time. Explicitly setting "/" means same-origin relative
// API calls (sandbox image: Caddy proxies /api/* on the same host — the
// trailing-slash strip turns "/" into ""); unset still defaults to localhost
// for local dev (?? instead of || so only *unset* falls back). Note: Next
// 14.2 skips inlining NEXT_PUBLIC_* vars whose value is falsy, so "" cannot
// be passed at build time directly — hence the "/" convention.
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

async function apiFetch(path: string, options: RequestInit = {}, useToken = true) {
  const headers: Record<string, string> = {
    ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers as Record<string, string>),
  };
  if (useToken) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---- Shared types ----
export type SharingMode = "anonymized" | "full";
export type DocumentScope = "room" | "knowledge";
export type LlmConfig = { provider: "local" | "anthropic"; model: string };
export type InsightCategory = { category: string; count: number };
export type InsightTrendPoint = { date: string; count: number };
export type InsightTopic = { label: string; count: number };
export type SharedConversation = { room_name: string; asked_at: string; question: string; answer: string };
export type Insights = {
  total_questions: number;
  by_category: InsightCategory[];
  trend: InsightTrendPoint[];
  top_topics: InsightTopic[];
  full_conversations: SharedConversation[];
};

// ---- LLM config ----
export async function getLlmConfig(): Promise<LlmConfig> {
  return apiFetch("/api/llm-config", {}, false);
}

// ---- Auth ----
export async function login(email: string, password: string) {
  return apiFetch("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false);
}
export async function register(email: string, password: string, name: string) {
  return apiFetch("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, name }) }, false);
}
export async function getMe() {
  return apiFetch("/api/auth/me");
}

// ---- Rooms ----
export async function getRooms() {
  return apiFetch("/api/rooms");
}
export async function createRoom(data: { name: string; description?: string; expires_at?: string }) {
  return apiFetch("/api/rooms", { method: "POST", body: JSON.stringify(data) });
}
export async function getRoom(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}`);
}
export async function updateRoom(roomId: string, data: Record<string, unknown>) {
  return apiFetch(`/api/rooms/${roomId}`, { method: "PATCH", body: JSON.stringify(data) });
}
export async function deleteRoom(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}`, { method: "DELETE" });
}

// ---- Documents ----
export type RoomDocument = {
  id: string;
  room_id: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  scope: DocumentScope;
  indexed: boolean;
  index_error?: string | null;
  chunks_count: number;
  created_at: string;
};
export async function uploadDocument(roomId: string, file: File, scope: DocumentScope = "room") {
  const form = new FormData();
  form.append("file", file);
  form.append("scope", scope);
  return apiFetch(`/api/rooms/${roomId}/documents`, { method: "POST", body: form });
}
export async function getDocuments(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}/documents`);
}
export async function deleteDocument(roomId: string, docId: string) {
  return apiFetch(`/api/rooms/${roomId}/documents/${docId}`, { method: "DELETE" });
}
// Recipient-facing: list the room's documents using the session token.
export async function getRecipientDocuments(roomId: string, sessionToken: string): Promise<RoomDocument[]> {
  return apiFetch(`/api/rooms/${roomId}/documents`, {
    headers: { Authorization: `Bearer ${sessionToken}` },
  }, false);
}
// Fetch the PDF itself as a Blob (works for sender JWT or recipient session
// token). Headers can't be set on an <iframe src>, so callers turn the blob
// into an object URL for viewing.
export async function fetchDocumentFile(
  roomId: string,
  docId: string,
  opts: { sessionToken?: string; withAppendix?: boolean } = {}
): Promise<Blob> {
  const token = opts.sessionToken || getToken();
  const qs = opts.withAppendix ? "?with_appendix=1" : "";
  const res = await fetch(`${API_BASE}/api/rooms/${roomId}/documents/${docId}/file${qs}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.blob();
}

// ---- Session lifecycle (recipient) ----
export async function closeSession(sessionToken: string) {
  return apiFetch("/api/session/close", {
    method: "POST",
    body: JSON.stringify({ session_token: sessionToken }),
  }, false);
}
// pagehide-safe variant: sendBeacon with a simple content type (text/plain)
// so the request survives page teardown without a CORS preflight.
export function closeSessionBeacon(sessionToken: string) {
  try {
    const blob = new Blob([JSON.stringify({ session_token: sessionToken })], { type: "text/plain" });
    navigator.sendBeacon(`${API_BASE}/api/session/close`, blob);
  } catch {}
}

// ---- Invites ----
export async function createInvite(roomId: string, data: { email: string; name?: string }) {
  return apiFetch(`/api/rooms/${roomId}/invites`, { method: "POST", body: JSON.stringify(data) });
}
export async function getMembers(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}/members`);
}
export async function revokeMember(roomId: string, memberId: string) {
  return apiFetch(`/api/rooms/${roomId}/members/${memberId}`, { method: "DELETE" });
}

// ---- Join ----
export async function getJoinInfo(token: string) {
  return apiFetch(`/api/join/${token}`, {}, false);
}
export async function verifyEmail(token: string, email: string) {
  return apiFetch(`/api/join/${token}/verify`, { method: "POST", body: JSON.stringify({ email }) }, false);
}
export async function confirmCode(token: string, email: string, code: string) {
  return apiFetch(`/api/join/${token}/confirm`, { method: "POST", body: JSON.stringify({ email, code }) }, false);
}
export async function acceptTerms(token: string, sessionToken: string, sharingMode?: SharingMode) {
  return apiFetch(`/api/join/${token}/accept`, {
    method: "POST",
    body: JSON.stringify({
      session_token: sessionToken,
      ...(sharingMode ? { sharing_mode: sharingMode } : {}),
    }),
  }, false);
}

// ---- Sharing mode (recipient session auth) ----
export async function setSharingMode(roomId: string, sharingMode: SharingMode, sessionToken: string) {
  return apiFetch(`/api/rooms/${roomId}/sharing-mode`, {
    method: "POST",
    headers: { Authorization: `Bearer ${sessionToken}` },
    body: JSON.stringify({ sharing_mode: sharingMode, session_token: sessionToken }),
  }, false);
}

// ---- Insights (sender JWT) ----
export async function getInsights(roomId?: string): Promise<Insights> {
  return apiFetch(`/api/insights${roomId ? `?room_id=${encodeURIComponent(roomId)}` : ""}`);
}

// ---- Q&A ----
export async function askQuestion(roomId: string, question: string, sessionToken?: string) {
  return apiFetch(`/api/rooms/${roomId}/qa`, {
    method: "POST",
    body: JSON.stringify({ question, session_token: sessionToken }),
  }, !sessionToken);
}

// ---- Audit ----
export async function getAuditLog(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}/audit`);
}
export async function exportAuditLog(roomId: string) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/rooms/${roomId}/audit/export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit_${roomId.slice(0, 8)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
