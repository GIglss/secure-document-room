"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getRooms, createRoom } from "@/lib/api";
import { getUser, clearAuth, isAuthenticated } from "@/lib/auth";

type Room = {
  id: string;
  name: string;
  description?: string;
  status: string;
  expires_at?: string;
  created_at: string;
  document_count: number;
  member_count: number;
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  expired: "bg-yellow-100 text-yellow-800",
  revoked: "bg-red-100 text-red-800",
  archived: "bg-gray-100 text-gray-700",
};

export default function Dashboard() {
  const router = useRouter();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", expires_at: "" });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const user = getUser();

  const loadRooms = useCallback(async () => {
    try {
      const data = await getRooms();
      setRooms(data);
    } catch {
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (!isAuthenticated()) { router.push("/login"); return; }
    loadRooms();
  }, [router, loadRooms]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setCreating(true);
    setError("");
    try {
      await createRoom({ name: form.name, description: form.description || undefined, expires_at: form.expires_at || undefined });
      setForm({ name: "", description: "", expires_at: "" });
      setShowCreate(false);
      loadRooms();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create room");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <span className="font-semibold text-blue-900">Secure Document Room</span>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">{user?.name}</span>
          <button onClick={() => { clearAuth(); router.push("/"); }} className="text-sm text-gray-500 hover:text-gray-700">Sign Out</button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">Secure Rooms</h1>
          <button onClick={() => setShowCreate(!showCreate)} className="bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-900 transition">
            + Create New Room
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6 shadow-sm">
            <h2 className="font-medium mb-4">New Secure Room</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Room Name *</label>
                <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Project Alpha Due Diligence" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Optional description" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Expiry Date (optional)</label>
                <input type="datetime-local" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              {error && <p className="text-red-600 text-sm">{error}</p>}
              <div className="flex gap-3">
                <button type="submit" disabled={creating} className="bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-900 disabled:opacity-60">
                  {creating ? "Creating..." : "Create Room"}
                </button>
                <button type="button" onClick={() => setShowCreate(false)} className="text-gray-600 px-4 py-2 text-sm hover:text-gray-900">Cancel</button>
              </div>
            </form>
          </div>
        )}

        {loading ? (
          <p className="text-gray-500 text-sm">Loading rooms...</p>
        ) : rooms.length === 0 ? (
          <div className="text-center py-20 text-gray-500">
            <p className="text-lg mb-2">No rooms yet</p>
            <p className="text-sm">Create your first secure room to share documents with external parties.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {rooms.map((room) => (
              <div key={room.id} className="bg-white border border-gray-200 rounded-xl p-6 flex items-center justify-between shadow-sm hover:border-blue-200 transition">
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="font-medium text-gray-900">{room.name}</h3>
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[room.status] || "bg-gray-100 text-gray-600"}`}>
                      {room.status}
                    </span>
                  </div>
                  {room.description && <p className="text-sm text-gray-500 mb-2">{room.description}</p>}
                  <div className="flex gap-4 text-xs text-gray-400">
                    <span>{room.document_count} document{room.document_count !== 1 ? "s" : ""}</span>
                    <span>{room.member_count} recipient{room.member_count !== 1 ? "s" : ""}</span>
                    <span>Created {new Date(room.created_at).toLocaleDateString()}</span>
                    {room.expires_at && <span>Expires {new Date(room.expires_at).toLocaleDateString()}</span>}
                  </div>
                </div>
                <Link href={`/dashboard/rooms/${room.id}`} className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-200 transition ml-4">
                  Open Room
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
