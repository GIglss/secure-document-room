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

### D-107 · No document viewer — Q&A only for recipients

**Decision:** Recipients have no way to view, paginate, or browse documents. The only interface is the Q&A chat.

**Rationale:** A document viewer, even a rendered PDF view, would expose raw content and create screenshot/print-to-PDF exfiltration vectors. The Q&A interface is the containment boundary. Future watermarked rendered views (post-MVP) would be an exception, designed specifically to embed recipient identity into every render.

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

## Open decisions (from handoff brief)

These are unresolved and should be addressed before Phase 2 design partner onboarding:

| # | Question | Why it matters |
|---|----------|---------------|
| OD-1 | Cloud LLM API vs. on-premise/confidential compute | Affects what the product can truthfully claim about data containment in sales conversations |
| OD-2 | Who creates the room — seller, sell-side advisor, or either? | Shapes sales motion and pricing model |
| OD-3 | Exact recipient terms legal text | The acceptance moment is the product's core legal mechanism; needs counsel review |
| OD-4 | In-room redaction vs. pre-upload redaction | Significant UX vs. engineering trade-off |
| OD-5 | Confidential compute partner (Tinfoil, Opaque, Anjuna) | Would enable cryptographically strong "no data leaves the room" claim |
| OD-6 | Product name and the verb | Category creation depends on it; should come from design partner conversations |
