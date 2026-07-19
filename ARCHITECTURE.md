# Architecture — Confidant (application internals)

This document covers the **application** running inside a sandbox. For the Azure topology (control plane, gold image, lifecycle) see [SAD.md](SAD.md); for operations see [infra/v2/OPERATIONS.md](infra/v2/OPERATIONS.md).

## Overview

Confidant is a per-client, disposable AI sandbox. Inside each sandbox VM the app enforces the product invariant: **all AI inference runs locally on the VM; no document content ever reaches an external LLM provider.** The client reads/downloads their document and asks a local model questions with grounded citations. Anonymized analytics are mirrored to durable control-plane storage before the VM is destroyed.

> **Terminology:** **provider** = the company/clinic/bank (code: "sender", JWT auth). **client** = the single invited individual (code: "recipient", session-token auth).

---

## Runtime topology (inside one sandbox VM)

```
Client / Provider ── HTTPS 443 ──► Caddy (auto-TLS)
                                     ├─► Next.js 14 frontend  (:3000)
                                     └─► FastAPI backend      (:8000, /api/*, /docs)
                                            ├─► llama.cpp server (:8080, OpenAI /v1) — Qwen3-8B Q4_K_M
                                            ├─► ChromaDB (local, all-MiniLM-L6-v2 embeddings)
                                            ├─► SQLite (relational state)
                                            └─► Azure Table Storage (managed identity, via private endpoint)
```

All services run as Docker containers from `docker-compose.sandbox.yml`, baked into the gold image. Config is injected at first boot via cloud-init (`runtime.env`): `PUBLIC_HOST`, `SANDBOX_ID`, `SECRET_KEY`, `ACS_*`.

---

## Backend (Python 3.12 · FastAPI · SQLite · ChromaDB)

### Entry point

`backend/main.py` — creates the FastAPI app, registers CORS + routers under `/api`. On startup (lifespan) it validates security-critical config, runs a lightweight auto-migration (adds v2 columns to existing tables), creates tables + `uploads/`/`data/chroma/` dirs, warms the embedding model, and re-indexes any documents left `indexed=false` (self-heal).

### Layers

```
Routes  (routes/*.py)      Thin HTTP layer — validate input, resolve auth, call services, log audit, respond
Services (services/*.py)   Business logic — document processing, RAG, insights, sessions, email, PDF appendix, audit
Models + Database          SQLAlchemy ORM over SQLite (sync SessionLocal)
Auth (auth.py)             JWT (python-jose) + bcrypt; get_current_user / get_optional_user dependencies
```

### Routes

| Module | Prefix | Purpose |
|--------|--------|---------|
| `routes/auth.py` | `/api/auth` | Provider registration, login, `/me` |
| `routes/rooms.py` | `/api/rooms` | Room CRUD, expiry, status; **`POST .../sharing-mode`** (client) |
| `routes/documents.py` | `/api/rooms/{id}/documents` | PDF upload (`scope=room\|knowledge`), list, delete, **`GET .../{id}/file[?with_appendix=1]`** |
| `routes/invites.py` | `/api/rooms/{id}/invites` | Invite creation, member list, revocation |
| `routes/join.py` | `/api/join/{token}` | Client join flow (verify → confirm → accept + sharing mode) |
| `routes/qa.py` | `/api/rooms/{id}/qa` | Grounded Q&A; provider JWT or client session; schedules insight classification |
| `routes/session.py` | `/api/session` | **`POST /close`** — end session (triggers sandbox destruction) |
| `routes/insights.py` | `/api/insights` | Aggregated analytics for the provider dashboard |
| `routes/audit.py` | `/api/rooms/{id}/audit` | Audit log retrieval + CSV export |

### Services

**`services/document_processor.py`** — PDF text extraction via `pypdf` (per-page blocks with `page_num`); `chunk_text()` → ~800-char word-boundary chunks. (v2 is PDF-only; DOCX/XLSX paths retired.)

**`services/rag_engine.py`** — vector store + LLM inference:
- ChromaDB persistent client at `./data/chroma/`; one collection per room (`room_{id}`) **plus** a shared `company_knowledge` collection keyed per sender id.
- Embeddings: singleton `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, local).
- Retrieval merges the room collection and the sender's knowledge rows, ranked by distance; a room with zero documents still answers from knowledge. Knowledge citations get a "(Company Knowledge)" suffix.
- Generation: pluggable `LLM_PROVIDER` — **`local`** (llama.cpp/OpenAI-compatible, default), `anthropic`, or legacy `mlx` alias. Strict system prompt (answer only from context, cite `[N]`, admit uncertainty).
- Grounding: `_ground_answer()` returns only the `[N]` sources actually cited; flags ungroundable answers `grounded=false`.

**`services/insights_service.py`** — after each answered question (FastAPI `BackgroundTasks`), classifies it via the active LLM into one of ten categories + a 3–8-word **PII-free** topic label; writes a `qa_insights` row (question/answer text only under `full` sharing) and mirrors it to Azure Table `insights`. Classification failure is logged and skipped — never breaks Q&A.

**`services/session_service.py`** — maintains a `session_activity` row per member (`logged_in_at`, `last_activity`, throttled to 1 write/60s, `status`); mirrors to Azure Table `sessions` keyed by `SANDBOX_ID`. This is what the control-plane cleanup timer consumes.

**`services/pdf_appendix.py`** — builds "Conversation Summary" pages (reportlab) from the client's Q&A history and merges them onto the original PDF (pypdf), with layered fallbacks (LLM down → verbatim list; generation fails → original PDF).

**`services/email_service.py`** — sends verification codes via ACS (`azure-communication-email`) when configured. ⚠️ Known issue: `begin_send` poller not awaited (see D-122 / SPEC §7).

**`services/audit_service.py`** — `log_event()` append-only insert; never updates/deletes. Now also logs `document_viewed`, `document_downloaded`, `session_closed`, `sharing_mode_changed`.

**`services/rate_limit.py`** — in-memory sliding-window limiter (Redis-swappable) for the Q&A path.

### Data stores

| Store | Technology | Location | Purpose | Survives VM? |
|-------|-----------|----------|---------|--------------|
| Relational DB | SQLite | `./secure_room.db` | Users, rooms, documents, members, audit, qa_insights, session_activity | ❌ dies with VM |
| Vector store | ChromaDB | `./data/chroma/` | Chunk embeddings (per-room + company_knowledge) | ❌ dies with VM |
| File storage | Local FS | `./uploads/{room_id}/` | Uploaded PDFs (served to client, audit-logged) | ❌ dies with VM |
| Analytics mirror | Azure Table `insights` | Control plane | Categories/topics (+ text if consented) | ✅ persists |
| Session state | Azure Table `sessions` | Control plane | Heartbeat/status for cleanup | ✅ persists |

---

## Frontend (Next.js 14 · TypeScript · Tailwind)

### Same-origin build
Built with `NEXT_PUBLIC_API_URL="/"` so one gold-image build serves every sandbox FQDN via relative `/api/*` calls (`src/lib/api.ts` uses `?? "http://localhost:8000"` + trailing-slash strip). See D-123 for why `""` doesn't work.

### Page routing

| Route | Who | Purpose |
|-------|-----|---------|
| `/` | Public | Landing (sovereign-sandbox messaging) |
| `/login` | Provider | Register / sign in |
| `/dashboard` | Provider | Room list; link to `/insights` |
| `/dashboard/rooms/[roomId]` | Provider | Documents (PDF upload + knowledge toggle), Access, Audit |
| `/insights` | Provider | Categories, 14-day trend, top topics, opted-in conversations |
| `/join/[token]` | Client | Verify → confirm → accept + **sharing-mode consent** |
| `/room/[roomId]` | Client | Document viewer + download, cited Q&A, sharing control, **End Session** |

### Client-side auth
- **Provider:** JWT in `localStorage` (`sdr_token`); checked on protected pages.
- **Client:** session token in `sessionStorage` (`sdr_session`) after join; cleared on exit/session close.

---

## Security model (v2)

The containment boundary moved from the browser to the **ephemeral, egress-locked VM**. Software controls layered on top:

| Threat | Mitigation |
|--------|-----------|
| Document content to external LLM | Local llama.cpp; sandbox subnet blocks outbound internet except ACME |
| Data persistence past engagement | VM + disk hard-deleted on session close / 15-min inactivity |
| Weights leaving the tenant | Baked into a CMK-encrypted gold image; no runtime fetch |
| Unauthorized room access | Email + `secrets`-random 6-digit code: expires (`CODE_TTL_MINUTES`), attempt-capped (`CODE_MAX_ATTEMPTS`), one-time, `compare_digest` |
| Replay / stale sessions | Session tokens `secrets.token_urlsafe(32)`, TTL (`SESSION_TTL_HOURS`), revoked on member revocation |
| Personal data exposure to provider | Anonymized categories by default; transcript text only under explicit `full` consent; classifier prompt excludes PII |
| Storage credential theft | Azure Storage is Entra-RBAC-only (`allowSharedKeyAccess=false`); managed identity; private endpoint |
| Forgeable JWTs | App refuses to start with default `SECRET_KEY` when `DEV_MODE=false`; per-sandbox key generated at spawn |
| Path traversal / upload abuse | Filename sanitization; PDF-only; ≤200 pages; ≤50 MB (413); empty-file rejection |
| Q&A bulk extraction | Per-accessor/per-room rate limiting (429) |
| Wrong citations | Grounding — only `[N]`-referenced sources returned; ungroundable flagged |
| Audit tampering | `audit_logs` insert-only; no update/delete path |
| Screenshot exfiltration | Not preventable at software layer — accountability (audit, terms) + ephemerality |

---

## Configuration

`backend/.env` (see `.env.example` for the full annotated list):

```
SECRET_KEY              JWT signing key (per-sandbox at spawn)
LLM_PROVIDER            local (default) | anthropic | mlx (alias)
LOCAL_LLM_BASE_URL      http://llamacpp:8080/v1
LOCAL_LLM_MODEL         qwen3-8b
DATABASE_URL            sqlite:///./secure_room.db
UPLOAD_DIR / CHROMA_DIR ./uploads · ./data/chroma
FRONTEND_URL            derived from PUBLIC_HOST in the sandbox
SANDBOX_ID              set by cloud-init; keys the sessions-table mirror
AZURE_TABLES_ENDPOINT   control-plane table endpoint (managed identity)
ACS_CONNECTION_STRING / ACS_SENDER_ADDRESS   verification email (optional)
MAX_PDF_PAGES / MAX_UPLOAD_BYTES             upload limits
```

---

## Upgrade paths

| Component | Current | Production path |
|-----------|---------|----------------|
| Database | SQLite (per-VM) | Postgres for a persistent provider control plane (v3) |
| Vector store | ChromaDB local | Fine as-is (per-VM, disposable) |
| LLM | Qwen3-8B on CPU (~8 tok/s) | GPU SKU (NCASv3_T4) + larger model as a new gallery image version |
| Email | ACS managed domain (deliverability open) | Branded sender domain (SPF/DKIM/DMARC) + awaited send poller |
| Rate limiting | In-memory (per-process) | Fine per-VM; Redis only if multi-worker |
| Audit immutability | Application-level | Azure Confidential Ledger |
| Concurrency | 2 sandboxes (quota) | Raise 10-vCPU regional cap |
