"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { askQuestion } from "@/lib/api";

type Citation = { document_name: string; page_ref?: string; excerpt: string };
type Message = { id: string; question: string; answer: string; citations: Citation[]; loading?: boolean };

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
  const [llmConfig, setLlmConfig] = useState<{ provider: string; model: string } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = sessionStorage.getItem("sdr_session");
    const storedRoomId = sessionStorage.getItem("sdr_room_id");
    if (!token || storedRoomId !== roomId) {
      router.push("/");
      return;
    }
    setSessionToken(token);
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/llm-config`)
      .then((r) => r.json())
      .then(setLlmConfig)
      .catch(() => {});
  }, [roomId, router]);

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
        prev.map((m) => m.id === tempId ? { ...m, answer: result.answer, citations: result.citations, loading: false } : m)
      );
      setActiveCitations(result.citations);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to get answer";
      setMessages((prev) => prev.map((m) => m.id === tempId ? { ...m, answer: `Error: ${msg}`, loading: false } : m));
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleExit = () => {
    sessionStorage.removeItem("sdr_session");
    sessionStorage.removeItem("sdr_room_id");
    router.push("/");
  };

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
                llmConfig.provider === "mlx"
                  ? "bg-green-50 border-green-200 text-green-700"
                  : "bg-blue-50 border-blue-200 text-blue-700"
              }`}
              title={llmConfig.provider === "mlx" ? "Running on local MLX model" : "Running on Anthropic API"}
            >
              {llmConfig.provider === "mlx" ? "Local MLX" : "Cloud"} · {llmConfig.model.split("/").pop()}
            </span>
          )}
        </div>
        <button onClick={handleExit} className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1.5 rounded-lg">
          Exit Room
        </button>
      </nav>

      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
            {messages.length === 0 && (
              <div className="text-center pt-16 text-gray-400">
                <p className="text-lg mb-2 font-medium text-gray-600">Ask about the documents</p>
                <p className="text-sm max-w-sm mx-auto">Your questions are answered by AI using the documents in this room. Answers are cited and synthesized — raw document content is never exposed.</p>
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
          </div>
        </div>

        {/* Citations panel */}
        <div className="w-72 border-l border-gray-200 bg-white flex flex-col flex-shrink-0 hidden lg:flex">
          <div className="px-4 py-3 border-b border-gray-100">
            <h3 className="text-sm font-medium text-gray-700">Source Citations</h3>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {activeCitations.length === 0 ? (
              <p className="text-xs text-gray-400 text-center pt-8">Ask a question to see relevant source citations.</p>
            ) : (
              activeCitations.map((c, i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold text-blue-800 bg-blue-50 w-5 h-5 rounded-full flex items-center justify-center">{i + 1}</span>
                    <span className="text-xs font-medium text-gray-700 truncate">{c.document_name}</span>
                  </div>
                  {c.page_ref && <p className="text-xs text-gray-400 mb-1">p.{c.page_ref}</p>}
                  <p className="text-xs text-gray-600 leading-relaxed">{c.excerpt}</p>
                </div>
              ))
            )}
          </div>
          <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400 text-center">
            This is a sealed environment. No documents can be downloaded.
          </div>
        </div>
      </div>
    </div>
  );
}
