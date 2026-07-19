"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  askQuestion, getLlmConfig, setSharingMode as apiSetSharingMode,
  getRecipientDocuments, fetchDocumentFile, closeSession, closeSessionBeacon,
  type LlmConfig, type SharingMode, type RoomDocument,
} from "@/lib/api";

type Citation = { number?: number; document_name: string; page_ref?: string; excerpt: string };
type Message = { id: string; question: string; answer: string; citations: Citation[]; grounded?: boolean; loading?: boolean };

export default function RoomQA() {
  const router = useRouter();
  const params = useParams();
  const roomId = params.roomId as string;

  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeCitations, setActiveCitations] = useState<Citation[]>([]);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [sharingMode, setSharingMode] = useState<SharingMode>("anonymized");
  const [sharingOpen, setSharingOpen] = useState(false);
  const [sharingSaving, setSharingSaving] = useState(false);
  const [docs, setDocs] = useState<RoomDocument[]>([]);
  const [docError, setDocError] = useState("");
  const [docBusy, setDocBusy] = useState<string>(""); // `${docId}:${action}` while fetching
  const [viewer, setViewer] = useState<{ url: string; name: string } | null>(null);
  const [sessionEnded, setSessionEnded] = useState(false);
  const sessionEndedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = sessionStorage.getItem("sdr_session");
    const storedRoomId = sessionStorage.getItem("sdr_room_id");
    if (!token || storedRoomId !== roomId) {
      router.push("/");
      return;
    }
    setSessionToken(token);
    const storedMode = sessionStorage.getItem("sdr_sharing_mode");
    if (storedMode === "anonymized" || storedMode === "full") setSharingMode(storedMode);
    getLlmConfig().then(setLlmConfig).catch(() => {});
    getRecipientDocuments(roomId, token).then(setDocs).catch(() => {});
  }, [roomId, router]);

  // Signal the sandbox cleanup listener when the page is closed/navigated away
  useEffect(() => {
    if (!sessionToken) return;
    const onPageHide = () => {
      if (!sessionEndedRef.current) closeSessionBeacon(sessionToken);
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, [sessionToken]);

  // Revoke the viewer object URL when it changes/unmounts
  useEffect(() => {
    return () => { if (viewer) URL.revokeObjectURL(viewer.url); };
  }, [viewer]);

  const handleViewDoc = useCallback(async (doc: RoomDocument) => {
    if (!sessionToken) return;
    setDocBusy(`${doc.id}:view`); setDocError("");
    try {
      // Headers can't be sent from an <iframe src>, so fetch the PDF as a
      // blob with the session token and view it via an object URL.
      const blob = await fetchDocumentFile(roomId, doc.id, { sessionToken });
      setViewer({ url: URL.createObjectURL(blob), name: doc.original_filename });
    } catch (err: unknown) {
      setDocError(err instanceof Error ? err.message : "Could not open document");
    } finally { setDocBusy(""); }
  }, [roomId, sessionToken]);

  const handleDownloadDoc = useCallback(async (doc: RoomDocument, withAppendix: boolean) => {
    if (!sessionToken) return;
    setDocBusy(`${doc.id}:${withAppendix ? "summary" : "download"}`); setDocError("");
    try {
      const blob = await fetchDocumentFile(roomId, doc.id, { sessionToken, withAppendix });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const stem = doc.original_filename.replace(/\.pdf$/i, "");
      a.download = withAppendix ? `${stem}_with_conversation_summary.pdf` : doc.original_filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setDocError(err instanceof Error ? err.message : "Download failed");
    } finally { setDocBusy(""); }
  }, [roomId, sessionToken]);

  const handleEndSession = async () => {
    if (!sessionToken) return;
    const ok = confirm(
      "End your session?\n\nThis closes your engagement: the isolated sandbox that processed your questions will be destroyed, and this link will no longer work. Download any documents you need before continuing."
    );
    if (!ok) return;
    try { await closeSession(sessionToken); } catch { closeSessionBeacon(sessionToken); }
    sessionEndedRef.current = true;
    sessionStorage.removeItem("sdr_session");
    sessionStorage.removeItem("sdr_room_id");
    sessionStorage.removeItem("sdr_sharing_mode");
    setSessionEnded(true);
  };

  const handleSharingChange = async (mode: SharingMode) => {
    if (mode === sharingMode || sharingSaving || !sessionToken) return;
    const previous = sharingMode;
    setSharingMode(mode);
    setSharingSaving(true);
    try {
      await apiSetSharingMode(roomId, mode, sessionToken);
      sessionStorage.setItem("sdr_sharing_mode", mode);
      setSharingOpen(false);
    } catch {
      setSharingMode(previous);
    } finally {
      setSharingSaving(false);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || loading || !sessionToken) return;
    setQuestion("");
    setError("");
    const tempId = Date.now().toString();
    const tempMsg: Message = { id: tempId, question: q, answer: "", citations: [], loading: true };
    setMessages((prev) => [...prev, tempMsg]);
    setActiveCitations([]);
    setLoading(true);
    try {
      const result = await askQuestion(roomId, q, sessionToken);
      setMessages((prev) =>
        prev.map((m) => m.id === tempId ? { ...m, answer: result.answer, citations: result.citations, grounded: result.grounded, loading: false } : m)
      );
      setActiveCitations(result.citations);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to get answer";
      setMessages((prev) => prev.map((m) => m.id === tempId ? { ...m, answer: `Error: ${msg}`, loading: false } : m));
      setError(
        /rate limit/i.test(msg)
          ? "You're sending questions too quickly. Please wait a moment before asking again."
          : msg
      );
    } finally {
      setLoading(false);
    }
  };

  const handleExit = () => {
    sessionStorage.removeItem("sdr_session");
    sessionStorage.removeItem("sdr_room_id");
    router.push("/");
  };

  const latestAnswered = [...messages].reverse().find((m) => !m.loading);

  if (sessionEnded) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm max-w-md w-full p-8 text-center">
          <div className="text-3xl mb-4">✓</div>
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Session ended</h1>
          <p className="text-sm text-gray-600 mb-4">
            Thank you for your review. The isolated sandbox that processed your questions is being destroyed —
            nothing from this engagement remains on a shared AI service.
          </p>
          <p className="text-xs text-gray-400">You can close this tab now.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-blue-900 text-sm">Secure Document Room</span>
          <span className="text-gray-400 text-sm">— Q&A Session</span>
          {llmConfig && (
            <span
              className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                llmConfig.provider === "local"
                  ? "bg-green-50 border-green-200 text-green-700"
                  : "bg-blue-50 border-blue-200 text-blue-700"
              }`}
              title={llmConfig.provider === "local" ? "Running on a local model — data never leaves the sandbox" : "Running on Anthropic API"}
            >
              {llmConfig.provider === "local"
                ? `Local model · ${llmConfig.model.split("/").pop()} — data never leaves the sandbox`
                : `Cloud · ${llmConfig.model.split("/").pop()}`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleExit} className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1.5 rounded-lg">
            Exit Room
          </button>
          <button onClick={handleEndSession} className="text-sm text-red-600 hover:text-red-800 border border-red-200 px-3 py-1.5 rounded-lg">
            End Session
          </button>
        </div>
      </nav>

      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
            {messages.length === 0 && (
              <div className="text-center pt-16 text-gray-400">
                <p className="text-lg mb-2 font-medium text-gray-600">Ask about the documents</p>
                <p className="text-sm max-w-sm mx-auto">Your questions are answered by AI using the documents in this room, with cited sources. You can also view or download the documents from the panel on the right. Your questions are processed by a local AI model inside an isolated sandbox that is destroyed after your engagement.</p>
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className="space-y-3">
                {/* Question */}
                <div className="flex justify-end">
                  <div className="bg-blue-800 text-white rounded-2xl rounded-tr-sm px-4 py-3 max-w-lg text-sm">
                    {msg.question}
                  </div>
                </div>
                {/* Answer */}
                <div
                  className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 max-w-2xl cursor-pointer hover:border-blue-200 transition"
                  onClick={() => setActiveCitations(msg.citations)}
                >
                  {msg.loading ? (
                    <div className="flex items-center gap-2 text-gray-400 text-sm">
                      <div className="flex gap-1">
                        {[0,1,2].map((i) => (
                          <div key={i} className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: `${i * 0.1}s` }} />
                        ))}
                      </div>
                      <span>Searching documents...</span>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">{msg.answer}</p>
                      {msg.citations.length > 0 && (
                        <p className="text-xs text-blue-600 mt-2 hover:underline">
                          {msg.citations.length} source{msg.citations.length !== 1 ? "s" : ""} — click to view citations
                        </p>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-200 bg-white px-6 py-4 flex-shrink-0">
            <div className="bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 text-xs text-amber-700 mb-3">
              AI answers are synthesized from room documents. Verify material facts against cited sources before making decisions.
            </div>
            {error && <p className="text-red-600 text-xs mb-2">{error}</p>}
            <form onSubmit={handleAsk} className="flex gap-3">
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a question about the documents..."
                disabled={loading}
                className="flex-1 border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={loading || !question.trim()}
                className="bg-blue-800 text-white px-5 py-3 rounded-xl text-sm font-medium hover:bg-blue-900 transition disabled:opacity-50"
              >
                Ask
              </button>
            </form>
            {/* Sharing mode — discreet control */}
            <div className="mt-2.5 text-xs text-gray-400 flex items-center gap-2">
              <span>
                Shared with the company:{" "}
                <span className="text-gray-500 font-medium">
                  {sharingMode === "full" ? "full conversation" : "anonymized topics only"}
                </span>
              </span>
              <button
                type="button"
                onClick={() => setSharingOpen((o) => !o)}
                className="text-blue-600 hover:underline"
              >
                {sharingOpen ? "Close" : "Change"}
              </button>
            </div>
            {sharingOpen && (
              <div className="mt-2 border border-gray-200 rounded-lg p-3 space-y-2 max-w-xl">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="radio" name="sharing_mode" checked={sharingMode === "anonymized"}
                    disabled={sharingSaving} onChange={() => handleSharingChange("anonymized")}
                    className="mt-0.5 h-4 w-4 border-gray-300 text-blue-800" />
                  <span className="text-xs text-gray-600">
                    <span className="font-medium text-gray-700">Share anonymized topics only.</span>{" "}
                    Only question categories and topic labels are shared — never your words or documents.
                  </span>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="radio" name="sharing_mode" checked={sharingMode === "full"}
                    disabled={sharingSaving} onChange={() => handleSharingChange("full")}
                    className="mt-0.5 h-4 w-4 border-gray-300 text-blue-800" />
                  <span className="text-xs text-gray-600">
                    <span className="font-medium text-gray-700">Share my full conversation.</span>{" "}
                    Helps the company understand your needs; you can change this anytime.
                  </span>
                </label>
              </div>
            )}
          </div>
        </div>

        {/* Documents + citations panel */}
        <div className="w-80 border-l border-gray-200 bg-white flex flex-col flex-shrink-0 hidden lg:flex">
          <div className="border-b border-gray-100">
            <div className="px-4 py-3 border-b border-gray-100">
              <h3 className="text-sm font-medium text-gray-700">Documents</h3>
            </div>
            <div className="px-4 py-3 space-y-2 max-h-64 overflow-y-auto">
              {docError && <p className="text-xs text-red-600">{docError}</p>}
              {docs.length === 0 ? (
                <p className="text-xs text-gray-400">No documents in this room yet.</p>
              ) : (
                docs.map((doc) => (
                  <div key={doc.id} className="border border-gray-200 rounded-lg p-3">
                    <p className="text-xs font-medium text-gray-700 truncate mb-2" title={doc.original_filename}>
                      {doc.original_filename}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        onClick={() => handleViewDoc(doc)}
                        disabled={docBusy !== ""}
                        className="text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-1 rounded hover:bg-blue-100 disabled:opacity-50"
                      >
                        {docBusy === `${doc.id}:view` ? "Opening…" : "View"}
                      </button>
                      <button
                        onClick={() => handleDownloadDoc(doc, false)}
                        disabled={docBusy !== ""}
                        className="text-xs bg-gray-50 text-gray-700 border border-gray-200 px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-50"
                      >
                        {docBusy === `${doc.id}:download` ? "Downloading…" : "Download"}
                      </button>
                      <button
                        onClick={() => handleDownloadDoc(doc, true)}
                        disabled={docBusy !== ""}
                        title="Download the PDF with appended pages summarizing your Q&A conversation in this room"
                        className="text-xs bg-gray-50 text-gray-700 border border-gray-200 px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-50"
                      >
                        {docBusy === `${doc.id}:summary` ? "Preparing…" : "Download with conversation summary"}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
          <div className="px-4 py-3 border-b border-gray-100">
            <h3 className="text-sm font-medium text-gray-700">Source Citations</h3>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {activeCitations.length === 0 ? (
              latestAnswered?.grounded === false ? (
                <p className="text-xs text-gray-400 text-center pt-8">This question could not be answered from the room documents.</p>
              ) : (
                <p className="text-xs text-gray-400 text-center pt-8">Ask a question to see relevant source citations.</p>
              )
            ) : (
              activeCitations.map((c, i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold text-blue-800 bg-blue-50 w-5 h-5 rounded-full flex items-center justify-center">{c.number ?? (i + 1)}</span>
                    <span className="text-xs font-medium text-gray-700 truncate">{c.document_name}</span>
                  </div>
                  {c.page_ref && <p className="text-xs text-gray-400 mb-1">p.{c.page_ref}</p>}
                  <p className="text-xs text-gray-600 leading-relaxed">{c.excerpt}</p>
                </div>
              ))
            )}
          </div>
          <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400 text-center">
            Your questions are processed by a local AI model inside an isolated sandbox that is destroyed after your engagement.
          </div>
        </div>
      </div>

      {/* PDF viewer modal */}
      {viewer && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 sm:p-8">
          <div className="bg-white rounded-xl shadow-xl w-full h-full max-w-5xl flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
              <span className="text-sm font-medium text-gray-700 truncate">{viewer.name}</span>
              <button
                onClick={() => setViewer(null)}
                className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1 rounded-lg"
              >
                Close
              </button>
            </div>
            <iframe src={viewer.url} title={viewer.name} className="flex-1 w-full" />
          </div>
        </div>
      )}
    </div>
  );
}
