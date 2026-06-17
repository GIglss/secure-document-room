"use client";
import Link from "next/link";

export default function Landing() {
  return (
    <div className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <span className="font-semibold text-lg text-blue-900">Secure Document Room</span>
        <Link href="/login" className="bg-blue-800 text-white px-4 py-2 rounded text-sm hover:bg-blue-900 transition">
          Sign In
        </Link>
      </nav>

      {/* Hero */}
      <div className="max-w-4xl mx-auto px-6 pt-24 pb-16 text-center">
        <div className="inline-block bg-amber-50 border border-amber-200 text-amber-800 text-xs font-medium px-3 py-1 rounded-full mb-6">
          New: February 2026 privilege-waiver ruling — using public AI on privileged docs can waive attorney-client privilege
        </div>
        <h1 className="text-5xl font-bold text-gray-900 leading-tight mb-6">
          The secure room where AI meets confidentiality
        </h1>
        <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto">
          Share confidential documents with external parties. Enable AI-powered Q&A. Neither side can extract content to a public AI model.
        </p>
        <Link href="/login" className="bg-blue-800 text-white px-8 py-4 rounded-lg text-lg font-medium hover:bg-blue-900 transition inline-block">
          Create Your First Room
        </Link>
      </div>

      {/* Features */}
      <div className="max-w-5xl mx-auto px-6 py-16 grid grid-cols-1 md:grid-cols-3 gap-8">
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-6">
          <div className="text-2xl mb-3">Sealed Environment</div>
          <p className="text-gray-600 text-sm">Documents never leave the controlled room. No download buttons. No raw file access. AI answers are synthesized, not raw text.</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-6">
          <div className="text-2xl mb-3">AI-Powered Q&A</div>
          <p className="text-gray-600 text-sm">Recipients ask natural language questions and get grounded, cited answers backed by the uploaded documents — without ever seeing raw content.</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-6">
          <div className="text-2xl mb-3">Full Audit Trail</div>
          <p className="text-gray-600 text-sm">Every access, every question, every action is logged in an immutable audit trail. Export as CSV for legal proceedings or compliance review.</p>
        </div>
      </div>

      {/* DocuSign analogy */}
      <div className="bg-blue-50 border-y border-blue-100 py-16">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <blockquote className="text-2xl font-medium text-blue-900 mb-4">
            "You use DocuSign to create a trusted envelope for signatures. This is the trusted envelope for AI-era document review."
          </blockquote>
          <p className="text-gray-600">In 2026, feeding a client's documents into a public AI model can waive attorney-client privilege. We built the room where neither side has to take that risk.</p>
        </div>
      </div>

      {/* Use cases */}
      <div className="max-w-4xl mx-auto px-6 py-16">
        <h2 className="text-2xl font-semibold text-center mb-10">Built for high-stakes document sharing</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {[
            ["M&A Due Diligence", "Sell-side shares data room with buyer. Buyer does AI-powered analysis without the seller fearing IP extraction."],
            ["Legal Document Review", "Counsel shares privileged documents with clients without risking privilege waiver through uncontrolled AI use."],
            ["Investment Banking", "Banks share confidential information memoranda with prospective buyers during deal processes."],
            ["PE & Co-investment", "Firms share portfolio company financials with co-investors or lenders under controlled conditions."],
          ].map(([title, desc]) => (
            <div key={title} className="flex gap-4">
              <div className="w-2 h-2 bg-blue-800 rounded-full mt-2 flex-shrink-0" />
              <div>
                <div className="font-medium mb-1">{title}</div>
                <div className="text-gray-600 text-sm">{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <footer className="border-t border-gray-200 py-8 text-center text-gray-400 text-sm">
        Secure Document Room — MVP Demo
      </footer>
    </div>
  );
}
