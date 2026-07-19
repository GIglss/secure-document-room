"use client";
import { useState, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import { getJoinInfo, verifyEmail, confirmCode, acceptTerms, type SharingMode } from "@/lib/api";

type Step = "info" | "verify" | "confirm" | "terms";

export default function JoinPage() {
  const router = useRouter();
  const params = useParams();
  const token = params.token as string;

  const [step, setStep] = useState<Step>("info");
  const [roomInfo, setRoomInfo] = useState<any>(null);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [demoCode, setDemoCode] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [roomId, setRoomId] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [sharingMode, setSharingMode] = useState<SharingMode>("anonymized");

  useEffect(() => {
    getJoinInfo(token)
      .then((info) => { setRoomInfo(info); setLoading(false); })
      .catch((err) => { setError(err.message || "Invalid invite link"); setLoading(false); });
  }, [token]);

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true); setError("");
    try {
      const result = await verifyEmail(token, email);
      setDemoCode(result.demo_code || "");
      setStep("confirm");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally { setSubmitting(false); }
  };

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true); setError("");
    try {
      const result = await confirmCode(token, email, code);
      setSessionToken(result.session_token);
      setRoomId(result.room_id);
      setStep("terms");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid code");
    } finally { setSubmitting(false); }
  };

  const handleAccept = async () => {
    if (!agreed) { setError("You must agree to the terms to enter."); return; }
    setSubmitting(true); setError("");
    try {
      await acceptTerms(token, sessionToken, sharingMode);
      sessionStorage.setItem("sdr_session", sessionToken);
      sessionStorage.setItem("sdr_room_id", roomId);
      sessionStorage.setItem("sdr_sharing_mode", sharingMode);
      router.push(`/room/${roomId}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to accept terms");
    } finally { setSubmitting(false); }
  };

  if (loading) return <div className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-500">Loading...</div>;

  if (!roomInfo && error) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white border border-red-200 rounded-xl p-8 max-w-md text-center">
        <p className="text-red-600 font-medium mb-2">Invalid Invite</p>
        <p className="text-gray-500 text-sm">{error}</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm w-full max-w-lg p-8">
        <div className="text-center mb-6">
          <div className="text-xs font-medium text-blue-800 bg-blue-50 border border-blue-200 px-3 py-1 rounded-full inline-block mb-3">
            Secure Document Room
          </div>
          <h1 className="text-xl font-semibold text-gray-900">{roomInfo?.room_name}</h1>
          {roomInfo?.description && <p className="text-gray-500 text-sm mt-1">{roomInfo.description}</p>}
          <p className="text-sm text-gray-400 mt-1">Shared by {roomInfo?.sender_name}</p>
        </div>

        {/* Step indicators */}
        <div className="flex items-center gap-2 mb-8 justify-center">
          {(["info", "confirm", "terms"] as const).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className={`w-6 h-6 rounded-full text-xs flex items-center justify-center font-medium ${
                step === s || (step === "verify" && s === "confirm") ? "bg-blue-800 text-white" :
                (["info"].indexOf(step) > ["info"].indexOf(s)) || (step !== "info" && s === "info") ? "bg-blue-200 text-blue-800" : "bg-gray-200 text-gray-500"
              }`}>{i + 1}</div>
              {i < 2 && <div className="w-8 h-px bg-gray-200" />}
            </div>
          ))}
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">{error}</div>}

        {/* Step: Info */}
        {step === "info" && (
          <div>
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 mb-6 text-sm text-blue-800">
              In this room you can view and download the shared documents and ask AI questions about them. Your questions are processed by a local AI model inside an isolated sandbox that is destroyed after your engagement. Your interactions are logged in an immutable audit trail.
            </div>
            <form onSubmit={handleVerify} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Your Email Address</label>
                <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="your@email.com" />
                <p className="text-xs text-gray-400 mt-1">Must match the email you were invited with.</p>
              </div>
              <button type="submit" disabled={submitting}
                className="w-full bg-blue-800 text-white py-2.5 rounded-lg font-medium hover:bg-blue-900 transition disabled:opacity-60">
                {submitting ? "Verifying..." : "Verify My Access"}
              </button>
            </form>
          </div>
        )}

        {/* Step: Confirm code */}
        {(step === "verify" || step === "confirm") && (
          <div>
            {demoCode && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4 text-sm">
                <p className="font-medium text-amber-800 mb-1">Demo Mode — Verification Code</p>
                <p className="text-amber-700">Your 6-digit code is: <span className="font-mono font-bold text-lg">{demoCode}</span></p>
                <p className="text-xs text-amber-600 mt-1">In production, this would be sent to your email.</p>
              </div>
            )}
            <form onSubmit={handleConfirm} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">6-Digit Verification Code</label>
                <input type="text" required value={code} onChange={(e) => setCode(e.target.value)}
                  maxLength={6} pattern="[0-9]{6}"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono tracking-widest text-center text-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="000000" />
              </div>
              <button type="submit" disabled={submitting}
                className="w-full bg-blue-800 text-white py-2.5 rounded-lg font-medium hover:bg-blue-900 transition disabled:opacity-60">
                {submitting ? "Confirming..." : "Confirm Code"}
              </button>
              <button type="button" onClick={() => setStep("info")} className="w-full text-sm text-gray-500 hover:text-gray-700 py-1">
                Use different email
              </button>
            </form>
          </div>
        )}

        {/* Step: Terms */}
        {step === "terms" && (
          <div>
            <h2 className="font-medium mb-3">Terms of Use</h2>
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs text-gray-700 font-mono whitespace-pre-wrap max-h-64 overflow-y-auto mb-4">
              {roomInfo?.terms_text}
            </div>
            <div className="flex items-start gap-3 mb-6">
              <input type="checkbox" id="agree" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-800" />
              <label htmlFor="agree" className="text-sm text-gray-700 cursor-pointer">
                I understand and agree to these terms. I acknowledge that my interactions will be logged.
              </label>
            </div>

            {/* Sharing consent */}
            <div className="border border-gray-200 rounded-lg p-4 mb-6">
              <h3 className="text-sm font-medium text-gray-700 mb-1">What is shared with {roomInfo?.sender_name || "the company"}?</h3>
              <p className="text-xs text-gray-400 mb-3">You can change this anytime from inside the room.</p>
              <div className="space-y-3">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="radio" name="sharing" checked={sharingMode === "anonymized"} onChange={() => setSharingMode("anonymized")}
                    className="mt-0.5 h-4 w-4 border-gray-300 text-blue-800" />
                  <span className="text-sm text-gray-700">
                    <span className="font-medium">Share anonymized topics only</span>
                    <span className="block text-xs text-gray-500 mt-0.5">
                      Only question categories and topic labels are shared with {roomInfo?.sender_name || "the company"} — never your words or documents.
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="radio" name="sharing" checked={sharingMode === "full"} onChange={() => setSharingMode("full")}
                    className="mt-0.5 h-4 w-4 border-gray-300 text-blue-800" />
                  <span className="text-sm text-gray-700">
                    <span className="font-medium">Share my full conversation</span>
                    <span className="block text-xs text-gray-500 mt-0.5">
                      Helps the company understand your needs; you can change this anytime.
                    </span>
                  </span>
                </label>
              </div>
            </div>
            <button onClick={handleAccept} disabled={submitting || !agreed}
              className="w-full bg-blue-800 text-white py-2.5 rounded-lg font-medium hover:bg-blue-900 transition disabled:opacity-60">
              {submitting ? "Entering room..." : "Enter the Room"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
