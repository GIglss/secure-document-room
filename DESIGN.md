# Design — Secure Document Room

Records product and engineering decisions made during the MVP build. Each entry explains what was decided and why, so future contributors can evaluate whether the rationale still applies before changing a decision.

---

## Product decisions

### D-001 · The DocuSign analogy as the product frame

**Decision:** Position the product as "the trusted envelope for AI-era document review," borrowing from DocuSign's category creation.

**Rationale:** DocuSign did not solve the photography problem — it created a trusted workflow with legal accountability. This product takes the same approach: it does not prevent all exfiltration, it creates a new category of accountable, contained AI-powered document review. The analogy shortens the sales cycle with deal lawyers and GCs who already understand DocuSign's value.

**Implication:** The product must always be honest about what it does not prevent (screenshots, manual transcription). The security claim is accountability and meaningful friction, not cryptographic guarantee.

---

### D-002 · Recipient terms acceptance as the accountability moment

**Decision:** Recipients must check a checkbox and click "Enter the Room" before accessing any Q&A. This step is logged in the audit trail.

**Rationale:** The handoff brief calls this "the DocuSign moment." It creates contractual liability for misuse. Without it, the product is just a Q&A chatbot. With it, a sender has a timestamped record that the counterparty explicitly agreed to the terms before accessing documents.

**Implication:** The terms text must be legally reviewed before production use. The MVP terms are a placeholder. The step must never be skippable or hidden (dark-pattern risk).

---

### D-003 · Answers are synthesized, never verbatim

**Decision:** The LLM system prompt explicitly forbids reproducing large verbatim passages. It instructs the model to paraphrase, cite, and signal uncertainty.

**Rationale:** This is the core containment mechanism at the AI layer. If the LLM returned raw document chunks, a recipient could assemble the full text through repeated queries. The synthesis requirement makes bulk extraction impractical.

**Known limitation:** A sufficiently patient attacker could still reconstruct content through many narrow queries. Rate limiting (post-MVP) provides an additional deterrent.

---

### D-004 · Beachhead: M&A due diligence and legal document review

**Decision:** The first design partners should be M&A boutiques or Am Law 200 firms.

**Rationale:** Highest pain, sharpest regulatory forcing function (February 2026 privilege-waiver ruling), existing VDR budget to displace, sophisticated buyers who understand risk, deal deadlines that create adoption urgency. Both parties (seller and buyer in M&A) are known actors with accountability relationships — reducing cold-start friction.

---

## Engineering decisions

### D-100 · SQLite for MVP persistence

**Decision:** Use SQLite via SQLAlchemy sync ORM. No PostgreSQL in MVP.

**Rationale:** Zero infrastructure setup. A single developer can run the full stack with `./start.sh` and no Docker. The SQLAlchemy ORM layer means the upgrade path to PostgreSQL is a one-line connection string change plus a migration. `pgvector` is deferred because ChromaDB runs locally and covers the vector use case without requiring a running Postgres instance.

**When to revisit:** Multiple concurrent backend processes; production deployment; when vector search needs to co-locate with relational queries for efficiency.

---

### D-101 · ChromaDB with DefaultEmbeddingFunction for vector storage

**Decision:** Use ChromaDB's built-in `DefaultEmbeddingFunction` (wraps `all-MiniLM-L6-v2` via sentence-transformers) for generating embeddings. Store persistently at `./data/chroma/`.

**Rationale:** No external API call for embeddings. The model runs locally inside the ChromaDB process. This keeps the document ingestion pipeline self-contained and free of Anthropic API dependency. `all-MiniLM-L6-v2` is sufficient for semantic search over legal and financial documents at MVP scale.

**When to revisit:** Quality of retrieval degrades on highly technical documents; when moving to a multi-instance deployment where a shared vector store is needed.

---

### D-102 · One ChromaDB collection per room

**Decision:** Each room gets its own ChromaDB collection named `room_{room_id}` (dashes replaced with underscores).

**Rationale:** Complete data isolation between rooms. A retrieval query for room A cannot accidentally surface content from room B. Deleting a room's documents (or the room itself) maps cleanly to deleting a single collection.

**Trade-off:** A deployment with thousands of rooms will accumulate thousands of small collections. ChromaDB handles this, but a shared multi-tenant collection with room-scoped metadata filtering would be more operationally efficient at scale. Accepted for MVP.

---

### D-103 · Background task for document indexing

**Decision:** Document upload returns immediately (HTTP 201) with `indexed: false`. Indexing runs in a FastAPI `BackgroundTasks` task.

**Rationale:** PDF/DOCX extraction and embedding generation can take seconds to minutes for large files. Blocking the upload response would create a poor UX. The frontend polls document status via the indexed flag.

**Known issue:** FastAPI `BackgroundTasks` run in the same process. Under load, they compete with request handlers. For production, move indexing to a separate worker queue (Celery, ARQ, or a simple database-polled worker).

---

### D-104 · Session tokens in sessionStorage (recipients) vs. localStorage (senders)

**Decision:** Recipient session tokens are stored in `sessionStorage`. Sender JWTs are stored in `localStorage`.

**Rationale:** Recipient access is scoped to a single deal review session. Using `sessionStorage` means the session is cleared when the tab closes — reducing the risk of an unattended browser giving ambient access to room content. Senders maintain persistent login because they manage rooms across multiple sessions.

**Trade-off:** Recipient must re-authenticate if they close and reopen the tab. Acceptable for a security-first product; the join flow is short.

---

### D-105 · Email verification code returned in API response (MVP only)

**Decision:** In the MVP, `POST /api/join/{token}/verify` returns the 6-digit verification code directly in the response body as `demo_code`. No email is sent.

**Rationale:** Avoids SMTP/SendGrid setup for the initial build. Enables testing the full flow without email infrastructure. The field name `demo_code` makes the temporary nature explicit in the API contract.

**Must change before production:** The `demo_code` field must be removed and a real email send must be wired in before any non-demo use. Leaving it in production would allow anyone who intercepts the API response to bypass email verification.

---

### D-106 · bcrypt directly (not passlib)

**Decision:** Password hashing uses the `bcrypt` library directly via `bcrypt.hashpw` / `bcrypt.checkpw`. Passlib was removed after a runtime incompatibility with newer bcrypt versions.

**Rationale:** Passlib 1.7.x has a bug where it fails to detect the bcrypt backend version on Python 3.12+, raising a `ValueError` during the first hash call. Direct `bcrypt` usage is simpler and avoids the compatibility layer entirely.

---

### D-107 · No document viewer — Q&A only for recipients — ⚠️ SUPERSEDED by D-120 (v2)

**Decision:** Recipients have no way to view, paginate, or browse documents. The only interface is the Q&A chat.

**Rationale:** A document viewer, even a rendered PDF view, would expose raw content and create screenshot/print-to-PDF exfiltration vectors. The Q&A interface is the containment boundary. Future watermarked rendered views (post-MVP) would be an exception, designed specifically to embed recipient identity into every render.

> **Reversed in v2 (D-120).** The product pivoted: the client is now *given* the document to read and download. The privacy guarantee moved from "hide the document" to "the model is local and the sandbox is destroyed." The containment boundary is now the ephemeral VM, not the browser.

---

### D-108 · Q&A rate limiting as a containment control

**Decision:** Every Q&A request is rate-limited per accessor, per room (`QA_RATE_MAX` requests per `QA_RATE_WINDOW_SECONDS`). Implemented as an in-memory sliding window in `services/rate_limit.py`.

**Rationale:** The handoff brief lists rate limiting in Component 6 (Enforcement layer) specifically to prevent "content extraction via repeated narrow queries." Without it, a recipient could reconstruct documents by asking thousands of targeted questions. The limit is a deterrent and a forcing function, not a hard wall.

**When to revisit:** Multi-worker deployment — the in-memory store is per-process. Swap for a Redis-backed counter with the same `check_rate_limit` interface.

---

### D-109 · Verification codes: expiry, attempt cap, single-use, DEV-gated demo

**Decision:** Codes are `secrets`-random, expire after `CODE_TTL_MINUTES`, are invalidated after `CODE_MAX_ATTEMPTS` failures, are cleared on first success, and are compared with `secrets.compare_digest`. The code is only returned in the API response when `DEV_MODE=true`.

**Rationale:** The original MVP returned the code unconditionally, which completely defeated email verification — anyone with a link could authenticate. A 6-digit code with no expiry or attempt cap is also brute-forceable. These changes make the identity check real while preserving the demo convenience behind an explicit flag.

**Must change before production:** Wire in real email sending; `DEV_MODE` must be `false`.

---

### D-110 · Recipient session TTL

**Decision:** Recipient session tokens (`secrets.token_urlsafe(32)`) expire `SESSION_TTL_HOURS` after terms acceptance and are checked on every Q&A request.

**Rationale:** Sessions previously lived forever until explicit revocation. A bounded lifetime limits the blast radius of a leaked token and matches the deal-scoped nature of recipient access (D-104).

---

### D-111 · Fail-fast on insecure production config

**Decision:** `config.validate_startup_config()` raises at startup if `SECRET_KEY` is the known default while `DEV_MODE=false`.

**Rationale:** A forgeable JWT signing key silently shipping to production is a critical risk. Failing loudly at boot is far safer than discovering it after deployment.

---

### D-112 · Upload hardening — filename sanitization and size cap

**Decision:** Upload filenames are reduced to a safe basename (alphanumerics, dot, dash, underscore) before being joined into a path; uploads over `MAX_UPLOAD_BYTES` are rejected with 413; empty files are rejected.

**Rationale:** The original `{doc_id}_{file.filename}` path join trusted user-supplied filenames (path-traversal risk) and had no size limit (DoS via huge uploads). The `doc_id` prefix made traversal unlikely but not impossible; sanitization removes the risk entirely.

---

### D-113 · Citation grounding and verification

**Decision:** After generation, `_ground_answer()` parses the `[N]` markers the answer actually used and returns only those sources (each carrying its marker `number`). Answers containing the model's "cannot answer from context" phrase are flagged `grounded=false` with no citations. If the model cites nothing, the top retrieved source is surfaced so there is always one verifiable reference.

**Rationale:** The brief calls citation accuracy critical: "a wrong citation is worse than no answer… a lawyer acting on a hallucinated clause reference could cause real harm." The original code returned all five retrieved chunks as citations regardless of what the answer used, implying support that may not exist. Grounding ties displayed citations to what the answer actually referenced.

**Limitation:** This verifies *which* sources were referenced, not that the claim is factually entailed by them. Stronger entailment-checking is a post-MVP enhancement.

---

### D-114 · Singleton embedding function

**Decision:** The ChromaDB embedding function is instantiated once at module level instead of on every `_get_collection` call.

**Rationale:** `DefaultEmbeddingFunction()` loads the all-MiniLM-L6-v2 model. Creating it per retrieval call risked repeated model setup on every question. A singleton loads it once per process.

---

### D-115 · Disable reasoning mode for the local MLX model

**Decision:** `_call_mlx()` disables the model's reasoning channel (`chat_template_kwargs.enable_thinking=False`, via `MLX_DISABLE_THINKING`, default true) and sets an explicit `MLX_MAX_TOKENS` (default 1024). It also strips any leaked `<think>…</think>` and falls back to the `reasoning` field if `content` is empty.

**Rationale:** Qwen3-class models emit a hidden `<think>` channel before answering. With `mlx_lm.server`'s default 512-token cap, the model consumed the entire budget thinking (`finish_reason: length`) and returned an empty `content` — surfacing to users as "Unable to generate answer." For an extraction-style RAG task the reasoning trace adds latency and token cost without improving short factual answers, so disabling it is the right default.

**When to revisit:** If retrieval-heavy multi-hop questions need deliberate reasoning, set `MLX_DISABLE_THINKING=false` and raise `MLX_MAX_TOKENS` so thinking and the answer both fit.

---

### D-116 · Self-healing document indexing

**Decision:** On startup the backend re-processes any document still marked `indexed=false` (per-document `OK`/`FAIL`/`SKIP` logging), and a failed extraction/index is recorded in `Document.index_error` rather than left silent. The frontend polls until indexed and shows a stalled hint after 25s.

**Rationale:** Indexing runs in a background task after upload; if the process crashed mid-index or the document was uploaded under older/broken code, it stayed `indexed=false` forever and the UI spun on "Processing" with no recourse. Self-heal on restart plus a recorded error makes the failure observable and recoverable.

**When to revisit:** Moving indexing to a dedicated worker queue (per D-103) — the re-index pass would become a queue replay instead.

---

---

## v2 decisions — sovereign ephemeral sandbox (2026-07-19)

The v2 pivot reframes the product from a *sealed two-party document room* to a *per-client, disposable AI sandbox on Azure running a local model*. Terminology: **provider** = the company/clinic/bank (code: "sender"); **client** = the single invited individual (code: "recipient").

### D-117 · One ephemeral VM per engagement, hard-deleted at the end

**Decision:** Each client engagement runs on its own Azure VM (`Standard_E4s_v6`) spawned from a gold image; the VM (+ NIC, public IP, disk) is hard-deleted on explicit session close or after 15 minutes of inactivity, by an Azure Functions timer.

**Rationale:** "The machine that held your data is destroyed" is a physical, demonstrable privacy guarantee — stronger than any contractual retention promise, and the core of the sales pitch. Per-VM isolation also means no shared runtime between clients (natural multi-tenancy) and bounds cost/blast-radius automatically.

**Trade-offs:** ~5–6 min spawn latency; max 2 concurrent sandboxes under the 10-vCPU regional cap; provider accounts live in the VM's SQLite and die with it (see D-119).

---

### D-118 · Local model (llama.cpp + Qwen3-8B) as the default provider

**Decision:** Default inference is llama.cpp serving Qwen3-8B (Q4_K_M GGUF) on the sandbox VM (`-t 4 --mlock --ctx-size 8192`), reached via its OpenAI-compatible endpoint. Anthropic and the legacy MLX path remain config switches. Weights are pre-baked into a CMK-encrypted gold image — never fetched at runtime.

**Rationale:** Data sovereignty is the product. A local model means no document text ever leaves the isolated VM, which has no outbound internet except ACME. Baking weights into the image keeps the sandbox subnet fully egress-locked. `llama.cpp` generalizes the earlier MLX/Ollama work to any GGUF and any host (D-115 reasoning-mode handling still applies conceptually).

**Alternative considered — Azure AI Foundry:** cheaper/faster, in-tenant with limited-retention terms, but a policy guarantee rather than a physical one. Kept as a one-env-var option for cost-sensitive engagements.

**When to revisit:** GPU quota (currently 0) would allow a larger/faster model; publish it as a new gallery image version.

---

### D-119 · Analytics persist off-VM; personal content only with consent

**Decision:** After each answered question, a background task classifies it into one of ten categories + a PII-free topic label and writes it to a control-plane Azure Table (`insights`) that survives VM destruction. Question/answer *text* is stored only when the client opted into `full` sharing (default is `anonymized`). A `sessions` table mirrors session state for the cleanup listener.

**Rationale:** The provider needs durable demand intelligence ("what do clients worry about") to improve sales/service, but the client's privacy is the product. Anonymized-by-default categories give the provider signal without exposing personal content; explicit opt-in unlocks transcripts. Persisting off-VM is the only way analytics can outlive the deliberately-destroyed sandbox.

**Implication:** Two new LLM call sites beyond Q&A (classification, and the appendix summary in D-121) — see `LLM_CALL_FLOW.md`. The classifier prompt must actively exclude names/companies/emails from the topic label.

---

### D-120 · Client can view and download the document (reverses D-107)

**Decision:** The client can view the PDF in-browser (auth'd blob → iframe) and download it. PDF-only, ≤200 pages, ≤50 MB. Every view/download is audit-logged.

**Rationale:** The v2 use case (a clinic/bank handing a client *their* document) requires the client to actually read it. With the containment boundary moved to the ephemeral VM (D-117), serving the file no longer breaks the privacy model — the file was always the client's to see.

---

### D-121 · Download with AI-generated conversation-summary appendix

**Decision:** `GET .../file?with_appendix=1` returns the original PDF plus appended "Conversation Summary" pages: an LLM-written summary of the client's Q&A history followed by the verbatim question list with answer excerpts (reportlab + pypdf). If the model is unreachable, it falls back to the verbatim list; if appendix generation fails entirely, it serves the original PDF. The download never fails.

**Rationale:** Gives the client a take-away record of their session that outlives the sandbox — useful, and reinforces the "you keep your data, we don't" story. Layered fallbacks keep a core action (getting your document) robust against model flakiness.

---

### D-122 · Real verification email via ACS (⚠️ deliverability open)

**Decision:** When `ACS_CONNECTION_STRING` + `ACS_SENDER_ADDRESS` are set, verification codes are emailed via Azure Communication Services and never returned in the API response (superseding the D-105 dev-mock for production). Credentials are fetched at spawn time and injected via cloud-init, never baked into the image.

**Rationale:** Real email is required for a real client onboarding; keeping the dev-mock behind absence-of-config preserves local testing.

**⚠️ Open item:** `services/email_service.py` calls `begin_send` without awaiting the poller, so async delivery failures are silent — in live testing ACS accepted the message but it did not arrive. Must await `.result()`, surface status, and likely use a branded (SPF/DKIM) sender domain before first client. Supersedes the production half of D-105; the dev-mock half stands.

---

### D-123 · Same-origin frontend build for a reusable image

**Decision:** The frontend is built with `NEXT_PUBLIC_API_URL="/"` so a single baked image serves every sandbox's unique FQDN via relative API calls; `src/lib/api.ts` uses `?? "http://localhost:8000"` (nullish, not `||`) plus a trailing-slash strip.

**Rationale:** Next.js inlines `NEXT_PUBLIC_*` at build time and *drops empty-string* values, so `""` would silently fall back to localhost. The `/` convention gives same-origin behavior while keeping the localhost default for local dev — letting one gold image work for all sandboxes without a per-FQDN rebuild.

---

## Open decisions (from handoff brief)

These are unresolved and should be addressed before Phase 2 design partner onboarding:

| # | Question | Why it matters | Status |
|---|----------|---------------|--------|
| OD-1 | Cloud LLM API vs. on-premise/confidential compute | Affects what the product can truthfully claim about data containment | **Resolved (v2):** local model on an ephemeral VM (D-118) is the default; Foundry/Anthropic a config switch |
| OD-2 | Who creates the room — seller, sell-side advisor, or either? | Shapes sales motion and pricing model | Open |
| OD-3 | Exact recipient terms legal text | The acceptance moment is the product's core legal mechanism; needs counsel review | Open (still placeholder) |
| OD-4 | In-room redaction vs. pre-upload redaction | Significant UX vs. engineering trade-off | Open |
| OD-5 | Confidential compute partner (Tinfoil, Opaque, Anjuna) | Would enable cryptographically strong "no data leaves the room" claim | Partially addressed: CMK image + egress-locked VM; confidential compute still future |
| OD-6 | Product name and the verb | Category creation depends on it | Working name: **Confidant** |
