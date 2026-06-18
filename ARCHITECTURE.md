# Architecture — Secure Document Room

## Overview

Secure Document Room is a sealed, AI-powered document sharing platform for two-party sensitive exchanges. The architecture enforces a single invariant: **raw document content never reaches the client browser**. All AI inference runs server-side; recipients interact only with synthesized answers and citations.

---

## Top-level structure

```
secure-document-room/
├── backend/          # Python 3.12 · FastAPI · SQLite · ChromaDB
├── frontend/         # Next.js 14 · TypeScript · Tailwind CSS
└── start.sh          # Development launcher (both servers)
```

The backend runs on port 8000. The frontend runs on port 3000 and proxies all `/api/*` requests to the backend via `next.config.ts` rewrites.

---

## Backend

### Entry point

`backend/main.py` — creates the FastAPI application, registers CORS middleware, mounts all routers under `/api`, and on startup creates DB tables and the `uploads/` and `data/chroma/` directories.

### Layers

```
┌────────────────────────────────────────────────────────────┐
│  Routes  (routes/*.py)                                      │
│  Thin HTTP layer — validates input, resolves auth,          │
│  calls services, logs audit events, returns responses       │
├────────────────────────────────────────────────────────────┤
│  Services  (services/*.py)                                  │
│  Business logic: document processing, RAG, audit logging    │
├────────────────────────────────────────────────────────────┤
│  Models  (models.py)  +  Database  (database.py)            │
│  SQLAlchemy ORM over SQLite; sync SessionLocal              │
├────────────────────────────────────────────────────────────┤
│  Auth  (auth.py)                                            │
│  JWT (python-jose) + bcrypt; two FastAPI dependencies       │
│  get_current_user (required) / get_optional_user (relaxed)  │
└────────────────────────────────────────────────────────────┘
```

### Routes

| Module | Prefix | Purpose |
|--------|--------|---------|
| `routes/auth.py` | `/api/auth` | Sender registration, login, `/me` |
| `routes/rooms.py` | `/api/rooms` | Room CRUD, expiry, status management |
| `routes/documents.py` | `/api/rooms/{id}/documents` | Upload, list, delete; triggers background indexing |
| `routes/invites.py` | `/api/rooms/{id}/invites` | Invite creation, member list, revocation |
| `routes/join.py` | `/api/join/{token}` | Recipient join flow (verify → confirm → accept) |
| `routes/qa.py` | `/api/rooms/{id}/qa` | Question answering; accepts sender JWT or recipient session token |
| `routes/audit.py` | `/api/rooms/{id}/audit` | Audit log retrieval and CSV export |

### Services

**`services/document_processor.py`**
Extracts text from uploaded files and splits into chunks:
- PDF → `pypdf` → per-page blocks with `page_num` metadata
- DOCX → `python-docx` → per-paragraph blocks with `section` metadata (heading-tracked)
- XLSX → `openpyxl` → per-sheet row-joined text with `sheet_name` metadata
- All formats → `chunk_text()` → ~800-character word-boundary chunks

**`services/rag_engine.py`**
Manages the vector store and LLM inference:
- ChromaDB persistent client at `./data/chroma/`
- One collection per room: `room_{room_id_with_underscores}`
- Embeddings: ChromaDB `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, runs locally)
- Retrieval: top-5 cosine similarity chunks for each question
- Generation: Anthropic `claude-sonnet-4-6` with a strict system prompt that forbids verbatim reproduction, requires citation notation, and mandates graceful uncertainty signaling

**`services/audit_service.py`**
Single function `log_event()` — inserts a row into `audit_logs`. Never updates or deletes rows. Called from every route that mutates state or serves Q&A.

### Data stores

| Store | Technology | Location | Purpose |
|-------|-----------|----------|---------|
| Relational DB | SQLite (SQLAlchemy) | `./secure_room.db` | Users, rooms, documents, members, audit logs |
| Vector store | ChromaDB (persistent) | `./data/chroma/` | Document chunk embeddings per room |
| File storage | Local filesystem | `./uploads/{room_id}/` | Raw uploaded files (never served to browser) |

---

## Frontend

### Entry point

`src/app/layout.tsx` — root Next.js App Router layout with Tailwind globals.

### Page routing

| Route | File | Who accesses it |
|-------|------|----------------|
| `/` | `app/page.tsx` | Public — marketing landing page |
| `/login` | `app/login/page.tsx` | Sender — register or sign in |
| `/dashboard` | `app/dashboard/page.tsx` | Sender (auth-gated) — room list |
| `/dashboard/rooms/[roomId]` | `app/dashboard/rooms/[roomId]/page.tsx` | Sender (auth-gated) — room management |
| `/join/[token]` | `app/join/[token]/page.tsx` | Recipient — multi-step join flow |
| `/room/[roomId]` | `app/room/[roomId]/page.tsx` | Recipient (session-gated) — Q&A interface |

### Client-side auth

- **Sender:** JWT stored in `localStorage` (`sdr_token`). `isAuthenticated()` checked on every protected page load; redirects to `/login` if absent.
- **Recipient:** `session_token` (UUID) stored in `sessionStorage` (`sdr_session`) after completing the join flow. Cleared on exit. Not persisted across tabs.

### API layer

`src/lib/api.ts` — all API calls go through typed `apiFetch()` wrapper that:
1. Attaches `Content-Type: application/json` (skipped for FormData)
2. Auto-injects `Authorization: Bearer {token}` from localStorage for sender routes
3. Parses error bodies for `detail` field
4. Returns `null` on 204

---

## Security model (MVP)

| Threat | Mitigation |
|--------|-----------|
| Raw file download | Files stored server-side only; no static file serving to clients; no download endpoint |
| Content extraction via Q&A | LLM prompt forbids verbatim reproduction; answers synthesized; **per-accessor/per-room rate limiting** (`QA_RATE_MAX`/`QA_RATE_WINDOW_SECONDS`) deters bulk extraction via repeated queries |
| Unauthorized room access | Email + 6-digit code before session issued. Code is `secrets`-random, **expires** (`CODE_TTL_MINUTES`), **attempt-capped** (`CODE_MAX_ATTEMPTS`, then invalidated), one-time, and compared with `compare_digest` |
| Verification-code brute force | Expiry + attempt cap + single-use; 429 on cap breach |
| Replay / stale sessions | Session tokens are `secrets.token_urlsafe(32)`, scoped to one `room_members` row, **expire** (`SESSION_TTL_HOURS`), revoked immediately on member revocation |
| Expired-room access | Expiry enforced on the Q&A path itself, not only on sender reload |
| Forgeable JWTs | App **refuses to start** with the default `SECRET_KEY` when `DEV_MODE=false` |
| Path traversal / upload abuse | Upload filenames sanitized to a safe basename; size cap (`MAX_UPLOAD_BYTES`, 413); empty files rejected |
| Credential bypass | Verification code only surfaced in API response when `DEV_MODE=true`; password policy enforced (min length, bcrypt 72-byte cap) |
| Wrong / unsupported citations | Answers grounded against retrieved sources; only `[N]`-referenced citations returned; ungroundable answers flagged `grounded=false` |
| Audit tampering | `audit_logs` rows are insert-only; no update/delete path exists in the codebase |
| Screenshot exfiltration | Not preventable at software layer — mitigated by watermarking (post-MVP), legal terms on acceptance, and audit trail |

---

## Configuration

All configuration lives in `backend/.env` (copy from `.env.example`):

```
SECRET_KEY          JWT signing key
ANTHROPIC_API_KEY   Required for Q&A (claude-sonnet-4-6)
DATABASE_URL        sqlite:///./secure_room.db (default)
UPLOAD_DIR          ./uploads (default)
CHROMA_DIR          ./data/chroma (default)
BASE_URL            http://localhost:8000
FRONTEND_URL        http://localhost:3000
```

---

## Post-MVP upgrade paths

| Component | MVP | Production path |
|-----------|-----|----------------|
| Database | SQLite | PostgreSQL + pgvector (enables vector search co-location) |
| Vector store | ChromaDB local | Pinecone / Weaviate for multi-instance deployments |
| File storage | Local filesystem | AWS S3 with SSE-S3 |
| Auth | Custom JWT | Auth0 / Clerk (adds SSO, MFA) |
| Email verification | Code returned in API response (`DEV_MODE` only) | SMTP / SendGrid |
| Rate limiting | In-memory sliding window (single process) | Redis-backed store for multi-worker / multi-instance |
| LLM | Anthropic cloud API | On-premise Llama / Mistral or confidential compute (Tinfoil, Opaque) for zero-knowledge claim |
| Deployment | Single process | Containerized; separate worker process for background indexing |
