"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import {
  getRoom, getDocuments, uploadDocument, deleteDocument,
  getMembers, createInvite, revokeMember,
  getAuditLog, exportAuditLog, updateRoom
} from "@/lib/api";
import { isAuthenticated, clearAuth, getUser } from "@/lib/auth";

type Tab = "documents" | "access" | "audit";

export default function RoomDetail() {
  const router = useRouter();
  const params = useParams();
  const roomId = params.roomId as string;
  const user = getUser();

  const [tab, setTab] = useState<Tab>("documents");
  const [room, setRoom] = useState<any>(null);
  const [docs, setDocs] = useState<any[]>([]);
  const [members, setMembers] = useState<any[]>([]);
  const [auditLog, setAuditLog] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [inviteForm, setInviteForm] = useState({ email: "", name: "" });
  const [inviteResult, setInviteResult] = useState<any>(null);
  const [inviting, setInviting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string>("");
  const [indexStalled, setIndexStalled] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const auditIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const copyLink = (link: string, key: string) => {
    navigator.clipboard.writeText(link);
    setCopied(key);
    setTimeout(() => setCopied(""), 2000);
  };

  const inviteLinkFor = (token: string) =>
    `${typeof window !== "undefined" ? window.location.origin : ""}/join/${token}`;

  const loadRoom = useCallback(async () => {
    try {
      const [r, d, m] = await Promise.all([getRoom(roomId), getDocuments(roomId), getMembers(roomId)]);
      setRoom(r); setDocs(d); setMembers(m);
    } catch { router.push("/dashboard"); }
    finally { setLoading(false); }
  }, [roomId, router]);

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return; }
    loadRoom();
  }, [router, loadRoom]);

  useEffect(() => {
    if (tab === "audit") {
      getAuditLog(roomId).then(setAuditLog).catch(() => {});
      auditIntervalRef.current = setInterval(() => getAuditLog(roomId).then(setAuditLog).catch(() => {}), 30000);
    }
    return () => { if (auditIntervalRef.current) clearInterval(auditIntervalRef.current); };
  }, [tab, roomId]);

  // Poll for indexing completion while any document is still processing.
  // Indexing runs server-side in the background after upload, so the list must
  // be re-fetched until every document reports indexed=true.
  useEffect(() => {
    const anyProcessing = docs.some((d) => !d.indexed && !d.index_error);
    if (!anyProcessing) { setIndexStalled(false); return; }
    const startedAt = Date.now();
    const interval = setInterval(async () => {
      try {
        setDocs(await getDocuments(roomId));
      } catch { /* keep polling */ }
      // If still processing after 25s, something is wrong server-side.
      if (Date.now() - startedAt > 25000) setIndexStalled(true);
    }, 2000);
    return () => clearInterval(interval);
  }, [docs, roomId]);

  const handleFileUpload = async (file: File) => {
    setUploading(true); setError("");
    try {
      await uploadDocument(roomId, file);
      const updated = await getDocuments(roomId);
      setDocs(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally { setUploading(false); }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviting(true); setError(""); setInviteResult(null);
    try {
      const result = await createInvite(roomId, { email: inviteForm.email, name: inviteForm.name || undefined });
      setInviteResult(result);
      setInviteForm({ email: "", name: "" });
      const updated = await getMembers(roomId);
      setMembers(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invite failed");
    } finally { setInviting(false); }
  };

  const handleRevoke = async (memberId: string) => {
    if (!confirm("Revoke this recipient's access?")) return;
    try {
      await revokeMember(roomId, memberId);
      setMembers(await getMembers(roomId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Revoke failed");
    }
  };

  const handleDeleteDoc = async (docId: string, filename: string) => {
    if (!confirm(`Delete "${filename}"?`)) return;
    try {
      await deleteDocument(roomId, docId);
      setDocs(await getDocuments(roomId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleCloseRoom = async () => {
    if (!confirm("Close this room? Recipients will lose access.")) return;
    try {
      await updateRoom(roomId, { status: "revoked" });
      loadRoom();
    } catch {}
  };

  if (loading) return <div className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-500">Loading...</div>;

  const STATUS_BADGE: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    expired: "bg-yellow-100 text-yellow-800",
    revoked: "bg-red-100 text-red-800",
    accepted: "bg-green-100 text-green-800",
    verified: "bg-yellow-100 text-yellow-800",
    invited: "bg-gray-100 text-gray-700",
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-gray-400 hover:text-gray-600 text-sm">← Rooms</Link>
          <span className="text-gray-300">/</span>
          <span className="font-medium text-gray-900">{room?.name}</span>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_BADGE[room?.status] || "bg-gray-100 text-gray-600"}`}>{room?.status}</span>
        </div>
        <div className="flex items-center gap-3">
          {room?.status === "active" && (
            <button onClick={handleCloseRoom} className="text-red-600 text-sm hover:text-red-800 border border-red-200 px-3 py-1.5 rounded-lg">Close Room</button>
          )}
          <span className="text-sm text-gray-500">{user?.name}</span>
          <button onClick={() => { clearAuth(); router.push("/"); }} className="text-sm text-gray-400 hover:text-gray-600">Sign Out</button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Room meta */}
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-gray-900 mb-1">{room?.name}</h1>
          {room?.description && <p className="text-gray-500 text-sm">{room.description}</p>}
          {room?.expires_at && <p className="text-xs text-gray-400 mt-1">Expires: {new Date(room.expires_at).toLocaleString()}</p>}
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">{error}</div>}

        {/* Tabs */}
        <div className="flex border-b border-gray-200 mb-6">
          {(["documents", "access", "audit"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition capitalize ${tab === t ? "border-blue-800 text-blue-800" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
              {t === "documents" ? `Documents (${docs.length})` : t === "access" ? `Access (${members.length})` : "Audit Log"}
            </button>
          ))}
        </div>

        {/* DOCUMENTS TAB */}
        {tab === "documents" && (
          <div>
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition mb-6"
            >
              <input ref={fileInputRef} type="file" accept=".pdf,.docx,.xlsx" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); }} />
              {uploading ? (
                <p className="text-blue-800 font-medium">Uploading and processing...</p>
              ) : (
                <>
                  <p className="font-medium text-gray-700 mb-1">Click or drag to upload</p>
                  <p className="text-sm text-gray-400">PDF, DOCX, or XLSX · Max 50MB</p>
                </>
              )}
            </div>
            {/* Readiness banner */}
            {docs.length > 0 && (
              docs.some((d) => !d.indexed && !d.index_error) ? (
                indexStalled ? (
                  <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-xs text-red-800 mb-6">
                    Indexing is taking longer than expected. This usually means the backend hit an error
                    while processing the file. Check the backend terminal for an <code className="bg-red-100 px-1 rounded">Indexing error</code> /
                    <code className="bg-red-100 px-1 rounded">FAIL</code> line, then restart the backend (it re-indexes pending documents on startup),
                    or remove and re-upload the file.
                  </div>
                ) : (
                  <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3 text-xs text-yellow-800 mb-6 flex items-center gap-2">
                    <span className="inline-block w-3 h-3 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
                    Indexing documents for AI Q&A — this updates automatically, no need to refresh.
                  </div>
                )
              ) : docs.some((d) => d.index_error) ? (
                <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-xs text-red-800 mb-6">
                  Some documents could not be indexed (see the error under each file below). Remove and
                  re-upload them, or upload a text-based version. Indexed documents are still usable for Q&A.
                </div>
              ) : (
                <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-xs text-green-800 mb-6">
                  All documents are indexed. Recipients can now ask questions in the room.
                </div>
              )
            )}
            {docs.length === 0 && (
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-700 mb-6">
                Documents are processed and indexed for AI Q&A. Raw files are never accessible to recipients.
              </div>
            )}
            {docs.length === 0 ? (
              <p className="text-gray-400 text-sm text-center py-8">No documents uploaded yet.</p>
            ) : (
              <div className="space-y-3">
                {docs.map((doc) => (
                  <div key={doc.id} className="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="font-medium text-sm">{doc.original_filename}</span>
                        <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded uppercase">{doc.file_type}</span>
                        {doc.indexed ? (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">
                            Ready · {doc.chunks_count} chunks
                          </span>
                        ) : doc.index_error ? (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700">
                            Indexing failed
                          </span>
                        ) : (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700 flex items-center gap-1">
                            <span className="inline-block w-2.5 h-2.5 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
                            Processing…
                          </span>
                        )}
                      </div>
                      {doc.index_error && !doc.indexed && (
                        <p className="text-xs text-red-600 mt-1 max-w-md">{doc.index_error}</p>
                      )}
                      <span className="text-xs text-gray-400">{(doc.file_size / 1024).toFixed(1)} KB · {new Date(doc.created_at).toLocaleDateString()}</span>
                    </div>
                    <button onClick={() => handleDeleteDoc(doc.id, doc.original_filename)}
                      className="text-red-400 hover:text-red-600 text-sm px-2">Remove</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ACCESS TAB */}
        {tab === "access" && (
          <div>
            <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
              <h3 className="font-medium mb-4">Invite Recipient</h3>
              <form onSubmit={handleInvite} className="flex gap-3 flex-wrap">
                <input type="email" required value={inviteForm.email} onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-48 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="recipient@firm.com" />
                <input type="text" value={inviteForm.name} onChange={(e) => setInviteForm({ ...inviteForm, name: e.target.value })}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Name (optional)" />
                <button type="submit" disabled={inviting} className="bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-900 disabled:opacity-60">
                  {inviting ? "Inviting..." : "Send Invite"}
                </button>
              </form>
              {inviteResult && (
                <div className="mt-4 bg-green-50 border border-green-200 rounded-lg p-3">
                  <p className="text-sm font-medium text-green-800 mb-1">Invite created — share this link with the recipient:</p>
                  <div className="flex items-center gap-2">
                    <input readOnly value={inviteResult.invite_link} className="text-xs text-gray-600 bg-white border border-gray-200 rounded px-2 py-1 flex-1" />
                    <button onClick={() => copyLink(inviteResult.invite_link, "new")}
                      className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded hover:bg-green-200 w-16">
                      {copied === "new" ? "Copied!" : "Copy"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {members.length === 0 ? (
              <p className="text-gray-400 text-sm text-center py-8">No recipients invited yet.</p>
            ) : (
              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      {["Email", "Name", "Status", "Invited", "Accepted", ""].map((h) => (
                        <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {members.map((m) => (
                      <tr key={m.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium">{m.email}</td>
                        <td className="px-4 py-3 text-gray-500">{m.name || "—"}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[m.status] || "bg-gray-100 text-gray-600"}`}>{m.status}</span>
                        </td>
                        <td className="px-4 py-3 text-gray-400 text-xs">{new Date(m.invited_at).toLocaleDateString()}</td>
                        <td className="px-4 py-3 text-gray-400 text-xs">{m.accepted_at ? new Date(m.accepted_at).toLocaleDateString() : "—"}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3 justify-end">
                            {m.status !== "revoked" && m.status !== "accepted" && (
                              <button onClick={() => copyLink(inviteLinkFor(m.invite_token), m.id)}
                                className="text-blue-600 hover:text-blue-800 text-xs">
                                {copied === m.id ? "Copied!" : "Copy link"}
                              </button>
                            )}
                            {m.status !== "revoked" && (
                              <button onClick={() => handleRevoke(m.id)} className="text-red-400 hover:text-red-600 text-xs">Revoke</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* AUDIT TAB */}
        {tab === "audit" && (
          <div>
            <div className="flex justify-between items-center mb-4">
              <p className="text-sm text-gray-500">All room events — immutable, append-only log</p>
              <button onClick={() => exportAuditLog(roomId)} className="text-sm border border-gray-300 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition">
                Export CSV
              </button>
            </div>
            {auditLog.length === 0 ? (
              <p className="text-gray-400 text-sm text-center py-8">No events logged yet.</p>
            ) : (
              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      {["Timestamp", "Event", "Details"].map((h) => (
                        <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {auditLog.map((e) => {
                      let details = "";
                      try { const d = JSON.parse(e.event_data || "{}"); details = Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(", "); } catch {}
                      return (
                        <tr key={e.id} className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                          <td className="px-4 py-3"><span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">{e.event_type}</span></td>
                          <td className="px-4 py-3 text-gray-500 text-xs max-w-xs truncate" title={details}>{details || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
