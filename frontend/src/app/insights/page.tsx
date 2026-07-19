"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getInsights, getRooms, type Insights } from "@/lib/api";
import { getUser, clearAuth, isAuthenticated } from "@/lib/auth";

type RoomOption = { id: string; name: string };

const CATEGORY_LABELS: Record<string, string> = {
  pricing: "Pricing",
  legal_terms: "Legal Terms",
  technical_capabilities: "Technical Capabilities",
  security_compliance: "Security & Compliance",
  integration: "Integration",
  support: "Support",
  timeline_delivery: "Timeline & Delivery",
  competitive_comparison: "Competitive Comparison",
  documentation_content: "Documentation Content",
  other: "Other",
};

function humanize(key: string): string {
  if (CATEGORY_LABELS[key]) return CATEGORY_LABELS[key];
  return key
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function TrendChart({ trend }: { trend: Insights["trend"] }) {
  const width = 560;
  const height = 120;
  const padX = 8;
  const padY = 12;
  if (trend.length === 0) {
    return <p className="text-gray-400 text-sm text-center py-8">No activity yet.</p>;
  }
  const max = Math.max(...trend.map((t) => t.count), 1);
  const stepX = trend.length > 1 ? (width - padX * 2) / (trend.length - 1) : 0;
  const points = trend.map((t, i) => {
    const x = trend.length > 1 ? padX + i * stepX : width / 2;
    const y = height - padY - (t.count / max) * (height - padY * 2);
    return { x, y, ...t };
  });
  const polyline = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `${padX},${height - padY} ${polyline} ${(points[points.length - 1]?.x ?? width - padX).toFixed(1)},${height - padY}`;
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-28" preserveAspectRatio="none" role="img" aria-label="Questions per day over the last 14 days">
        <polygon points={area} className="fill-blue-100" />
        <polyline points={polyline} fill="none" className="stroke-blue-700" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p) => (
          <circle key={p.date} cx={p.x} cy={p.y} r={2.5} className="fill-blue-700">
            <title>{`${p.date}: ${p.count} question${p.count !== 1 ? "s" : ""}`}</title>
          </circle>
        ))}
      </svg>
      <div className="flex justify-between text-xs text-gray-400 mt-1">
        <span>{trend[0].date}</span>
        <span>{trend[trend.length - 1].date}</span>
      </div>
    </div>
  );
}

export default function InsightsPage() {
  const router = useRouter();
  const user = getUser();
  const [insights, setInsights] = useState<Insights | null>(null);
  const [rooms, setRooms] = useState<RoomOption[]>([]);
  const [roomFilter, setRoomFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadInsights = useCallback(async (roomId: string) => {
    setLoading(true);
    setError("");
    try {
      setInsights(await getInsights(roomId || undefined));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load insights");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return; }
    loadInsights("");
    getRooms().then((r: RoomOption[]) => setRooms(r)).catch(() => {});
  }, [router, loadInsights]);

  const maxCategory = insights ? Math.max(...insights.by_category.map((c) => c.count), 1) : 1;

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-gray-400 hover:text-gray-600 text-sm">← Rooms</Link>
          <span className="text-gray-300">/</span>
          <span className="font-medium text-gray-900">Insights</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">{user?.name}</span>
          <button onClick={() => { clearAuth(); router.push("/"); }} className="text-sm text-gray-500 hover:text-gray-700">Sign Out</button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Question Insights</h1>
            <p className="text-sm text-gray-500 mt-1">What your clients are asking across your secure rooms.</p>
          </div>
          <select
            value={roomFilter}
            onChange={(e) => { setRoomFilter(e.target.value); loadInsights(e.target.value); }}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All rooms</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">{error}</div>}

        {loading ? (
          <p className="text-gray-500 text-sm">Loading insights...</p>
        ) : insights ? (
          <div className="space-y-6">
            {/* Stat header */}
            <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Total Questions Asked</p>
              <p className="text-4xl font-semibold text-gray-900">{insights.total_questions}</p>
            </div>

            <div className="grid md:grid-cols-2 gap-6">
              {/* Category bar chart */}
              <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
                <h2 className="font-medium text-gray-900 mb-4">Questions by Category</h2>
                {insights.by_category.length === 0 ? (
                  <p className="text-gray-400 text-sm text-center py-8">No questions categorized yet.</p>
                ) : (
                  <div className="space-y-3">
                    {insights.by_category.map((c) => (
                      <div key={c.category}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-gray-600 font-medium">{humanize(c.category)}</span>
                          <span className="text-gray-400">{c.count}</span>
                        </div>
                        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-700 rounded-full"
                            style={{ width: `${Math.max((c.count / maxCategory) * 100, 2)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 14-day trend */}
              <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
                <h2 className="font-medium text-gray-900 mb-4">14-Day Trend</h2>
                <TrendChart trend={insights.trend} />
              </div>
            </div>

            {/* Top topics */}
            <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
              <h2 className="font-medium text-gray-900 mb-4">Top Topics</h2>
              {insights.top_topics.length === 0 ? (
                <p className="text-gray-400 text-sm text-center py-8">No topics yet — they appear as clients ask questions.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {insights.top_topics.map((t) => (
                    <span key={t.label} className="inline-flex items-center gap-1.5 bg-blue-50 border border-blue-100 text-blue-800 text-sm px-3 py-1.5 rounded-full">
                      {t.label}
                      <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-medium">{t.count}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Shared conversations */}
            <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
              <h2 className="font-medium text-gray-900 mb-1">Shared Conversations</h2>
              <p className="text-xs text-gray-400 mb-4">Full questions and answers from clients who opted into full conversation sharing.</p>
              {insights.full_conversations.length === 0 ? (
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-6 text-center">
                  <p className="text-sm text-gray-500 mb-1">No shared conversations yet.</p>
                  <p className="text-xs text-gray-400 max-w-md mx-auto">
                    Conversations appear here only when a client opts into sharing their full conversation.
                    By default, clients share anonymized topics only.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {insights.full_conversations.map((c, i) => (
                    <div key={i} className="border border-gray-200 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
                        <span className="text-xs font-medium text-gray-500">{c.room_name}</span>
                        <span className="text-xs text-gray-400">{new Date(c.asked_at).toLocaleString()}</span>
                      </div>
                      <p className="text-sm text-gray-900 font-medium mb-2">{c.question}</p>
                      <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{c.answer}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
