import { getToken } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
export async function uploadDocument(roomId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/api/rooms/${roomId}/documents`, { method: "POST", body: form });
}
export async function getDocuments(roomId: string) {
  return apiFetch(`/api/rooms/${roomId}/documents`);
}
export async function deleteDocument(roomId: string, docId: string) {
  return apiFetch(`/api/rooms/${roomId}/documents/${docId}`, { method: "DELETE" });
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
export async function acceptTerms(token: string, sessionToken: string) {
  return apiFetch(`/api/join/${token}/accept`, { method: "POST", body: JSON.stringify({ session_token: sessionToken }) }, false);
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
