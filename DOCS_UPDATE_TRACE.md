# Documentation Update Trace — Integration Fixes: MLX Q&A, Indexing Self-Heal, Q&A Error Surfacing

> Generated June 17, 2026.
> Purpose: Records live-testing bug fixes that make the stack work end-to-end on a local MLX model — the Q&A "Failed to fetch" / empty-answer issues, the "document stuck on Processing" issue, and the supporting UX.
> Status: **APPLIED** (code) — June 17, 2026. **Not yet committed** — commit + push deferred per request.

---

## What Changed in the Codebase

### Modified files

**LLM provider — local MLX**
- `backend/services/rag_engine.py` — `_call_mlx()` now disables reasoning-model thinking (`extra_body={"chat_template_kwargs": {"enable_thinking": False}}`) and sets `max_tokens` (`MLX_MAX_TOKENS`, default 1024). Root cause: Qwen3 spent the entire default 512-token budget in a `reasoning`/`<think>` channel (`finish_reason: length`), leaving `content` empty → "Unable to generate answer." Added `_strip_think()` and a reasoning-channel fallback. `_call_anthropic()` now detects the placeholder key (`startswith("your-")`) and raises an actionable error.
- `backend/.env.example` — switched documentation to MLX-first; added `MLX_MAX_TOKENS` and `MLX_DISABLE_THINKING` knobs. (Live `backend/.env` set to `LLM_PROVIDER=mlx`, `MLX_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit`; `.env` is gitignored.)

**Q&A error surfacing**
- `backend/routes/qa.py` — wraps `answer_question()` in try/except → `503` for config errors (missing/placeholder key) and `502` for provider/network failures. Unhandled 500s skip CORS headers, so the browser saw a generic "Failed to fetch"; handled exceptions carry CORS headers and a readable `detail`.

**Document indexing — self-heal + visibility**
- `backend/main.py` — startup `_reindex_pending_documents()` re-processes any `indexed=false` documents on boot with per-document `OK`/`FAIL`/`SKIP` logging (fixes documents left stuck by a prior crash/old code); warms the embedding model at startup so the first upload doesn't pay the load cost mid-request.
- `backend/models.py` / `backend/schemas.py` — `Document.index_error` (+ `DocumentOut.index_error`) so a failed extraction/index is recorded and visible instead of spinning forever.

**Frontend UX**
- `frontend/src/app/dashboard/rooms/[roomId]/page.tsx` — polls the document list every 2s until all docs report `indexed=true` (fixes "stuck on Processing — updates automatically" never updating); readiness banner (indexing / all-indexed / stalled-after-25s with an actionable hint); per-member invite-link re-copy with "Copied!" feedback.
- `backend/schemas.py` — `MemberOut.invite_token` exposed so the sender can re-copy a recipient's join link.

## Documentation Changes

| File | What was updated |
|------|-----------------|
| `ARCHITECTURE.md` | Startup lifespan now lists config validation, embedding warm-up, and self-heal re-index; `rag_engine` generation described as provider-pluggable (Anthropic / local MLX) + grounding |
| `DESIGN.md` | Added D-115 (disable MLX reasoning mode) and D-116 (self-healing document indexing) |
| `LLM_CALL_FLOW.md` | MLX branch documents `enable_thinking=False` + `MLX_MAX_TOKENS` + `_strip_think`/reasoning fallback; new reasoning-models subsection; config table adds the two MLX knobs; failure-modes table rewritten to handled 502/503 (CORS-safe) + 429 |
| `HOW_DOES_ALL_CONVERGE.md` | Q&A flow shows provider choice + grounding + handled error path; background-indexing concept notes `index_error` and startup self-heal |
| `README.md` | No changes |

---

# Documentation Update Trace — Hardening Pass: Security, RAG Grounding, Efficiency

> Generated June 17, 2026.
> Purpose: Records a review-driven hardening pass against the handoff brief covering security, architecture/logic, efficiency, and functionality.
> Status: **APPLIED** — June 17, 2026.

---

## What Changed in the Codebase

### New files
- `backend/config.py` — centralized settings + `validate_startup_config()` (refuses default `SECRET_KEY` when `DEV_MODE=false`); policy constants for codes, sessions, rate limiting, uploads, passwords
- `backend/services/rate_limit.py` — in-memory sliding-window rate limiter (Redis-swappable interface)

### Modified files
**Milestone 1 — Security**
- `backend/routes/join.py` — verification code is now `secrets`-random, expires (`CODE_TTL_MINUTES`), capped at `CODE_MAX_ATTEMPTS` (429 + invalidation), one-time (cleared on success); `demo_code` only returned when `DEV_MODE`; session token is `secrets.token_urlsafe(32)` with `SESSION_TTL_HOURS` expiry; `compare_digest` used for code check
- `backend/routes/qa.py` — enforces room expiry on the Q&A path itself; checks recipient session expiry; per-accessor/per-room rate limiting (429); rejects empty questions
- `backend/routes/documents.py` — filename sanitization (path-traversal safe), max upload size (`MAX_UPLOAD_BYTES`, 413), empty-file rejection
- `backend/routes/auth.py` — `validate_password()` on register
- `backend/auth.py` — reads `SECRET_KEY` from config; password policy helper; `verify_password` guards bcrypt `ValueError`
- `backend/models.py` — `RoomMember` gains `code_expires_at`, `verification_attempts`, `session_expires_at`

**Milestone 2 — RAG citation grounding**
- `backend/services/rag_engine.py` — `_ground_answer()` parses `[N]` markers, returns only the cited sources (each carrying its marker `number`), flags ungroundable answers (`grounded=false`); singleton embedding function
- `backend/schemas.py` — `Citation.number`, `QAResponse.grounded`
- `frontend/src/app/room/[roomId]/page.tsx` — renders citation numbers from markers, friendly 429 banner, "could not be answered" panel state

**Milestone 3 — Efficiency & architecture**
- `backend/services/rag_engine.py` — embedding model loaded once (was per-query)
- `backend/routes/documents.py` — background indexer reuses `SessionLocal` (was a new engine per upload)
- `backend/main.py` — `lifespan` handler (replaces deprecated `on_event`), runs startup config validation
- `backend/routes/rooms.py` — room list uses aggregate `COUNT` queries (was loading every relationship row)
- `backend/routes/audit.py` — `limit`/`offset` pagination
- `backend/.env.example` — documents all new policy variables

## Documentation Changes

| File | What was updated |
|------|-----------------|
| `ARCHITECTURE.md` | Security model table expanded with new controls (rate limiting, code/session policy, upload limits, startup guard) |
| `DESIGN.md` | New decisions D-108 to D-114 (security hardening + grounding) |
| `LLM_CALL_FLOW.md` | Added citation-grounding step and `grounded` flag to the flow |
| `HOW_DOES_ALL_CONVERGE.md` | No changes — flow and entry points unchanged |

---

# Documentation Update Trace — MVP: Secure Document Room Initial Build

> Generated June 16, 2026.
> Purpose: Records the complete initial implementation of the Secure Document Room MVP — a sealed, AI-powered two-party document sharing platform built from the product handoff brief.
> Status: **APPLIED** — June 16, 2026.

---

## What Changed in the Codebase

### New files

**Backend (`backend/`)**
- `main.py` — FastAPI app entry point; CORS, router registration, startup hooks (DB init, dir creation)
- `database.py` — SQLAlchemy engine + `SessionLocal` + `get_db` dependency; SQLite by default
- `models.py` — ORM models: `User`, `Room`, `Document`, `RoomMember`, `AuditLog`
- `schemas.py` — Pydantic v2 request/response schemas for all entities
- `auth.py` — JWT creation/decoding (python-jose), bcrypt password hashing, `get_current_user` / `get_optional_user` FastAPI dependencies
- `pyproject.toml` — uv-managed Python 3.11+ project; deps: fastapi, uvicorn, sqlalchemy, python-jose, bcrypt, python-multipart, anthropic, pypdf, python-docx, openpyxl, chromadb
- `routes/auth.py` — `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- `routes/rooms.py` — Room CRUD: list, create, get, patch, delete (sets status=revoked); auto-expiry check on every read
- `routes/documents.py` — Multipart upload (PDF/DOCX/XLSX only); saves to `uploads/{room_id}/`; triggers background indexing task; list and delete
- `routes/invites.py` — Create invite (generates UUID token + invite link), list members, revoke member
- `routes/join.py` — Recipient join flow: `GET /api/join/{token}` (room info + terms), `POST .../verify` (email match → 6-digit code, returned in response for MVP demo), `POST .../confirm` (code check → session_token), `POST .../accept` (sets status=accepted)
- `routes/qa.py` — `POST /api/rooms/{id}/qa`; resolves access for sender (JWT) or recipient (session_token); delegates to RAG engine; logs every question to audit
- `routes/audit.py` — `GET /api/rooms/{id}/audit` (list events newest-first), `GET .../audit/export` (CSV StreamingResponse)
- `services/document_processor.py` — Text extraction: `pypdf` for PDF (per-page), `python-docx` for DOCX (per-paragraph with heading tracking), `openpyxl` for XLSX (per-sheet row join); `chunk_text()` splits into ~800-char chunks preserving metadata
- `services/rag_engine.py` — ChromaDB persistent client at `./data/chroma/`; `DefaultEmbeddingFunction` (all-MiniLM-L6-v2); `index_document()` upserts chunks per room collection; `answer_question()` queries top-5 chunks → Anthropic `claude-sonnet-4-6` with strict system prompt (no raw text reveal, cite sources, admit uncertainty)
- `services/audit_service.py` — `log_event()` append-only insert; never updates rows

**Frontend (`frontend/`)**
- `src/app/layout.tsx` — Root layout with Tailwind globals
- `src/app/globals.css` — Tailwind base/components/utilities
- `src/app/page.tsx` — Landing page: hero, 3 feature cards (Sealed/AI Q&A/Audit), DocuSign analogy quote, privilege-waiver ruling banner, 4 use-case items
- `src/app/login/page.tsx` — Sign In / Create Account tabs; stores JWT + user in localStorage on success
- `src/app/dashboard/page.tsx` — Protected room list; inline create-room form; status badges; links to room detail
- `src/app/dashboard/rooms/[roomId]/page.tsx` — 3-tab room management: Documents (drag-drop upload, indexing status, delete), Access (invite form with link copy, members table with revoke), Audit Log (event table, CSV export, 30s auto-refresh)
- `src/app/join/[token]/page.tsx` — 3-step recipient join: email entry → 6-digit code (demo code shown inline) → terms acceptance (checkbox gate)
- `src/app/room/[roomId]/page.tsx` — Q&A interface: chat history with loading dots, citations side-panel (desktop), session_token from sessionStorage, exit button
- `src/lib/api.ts` — Typed fetch wrappers for all API endpoints; auto-attaches Bearer token from localStorage; handles 204 and error bodies
- `src/lib/auth.ts` — localStorage helpers: `getToken`, `getUser`, `setAuth`, `clearAuth`, `isAuthenticated`
- `next.config.ts` — `/api/*` rewrite proxy to `http://localhost:8000`
- `tailwind.config.ts`, `postcss.config.js`, `tsconfig.json`, `package.json` — Next.js 14 + Tailwind CSS project config

**Root**
- `start.sh` — Launches backend (`uv run uvicorn`) and frontend (`npm run dev`) concurrently; traps Ctrl+C to kill both

## Documentation Changes

| File | What was updated |
|------|-----------------|
| `ARCHITECTURE.md` | Created — full system architecture: layers, routes, services, data stores, security model, config, upgrade paths |
| `DESIGN.md` | Created — 7 engineering decisions (D-100 to D-106) + 4 product decisions (D-001 to D-004) + 6 open decisions from handoff brief |
| `LLM_CALL_FLOW.md` | Created — full call flow diagram, system prompt text, token budget, failure modes, future call sites |
| `HOW_DOES_ALL_CONVERGE.md` | Created — entry points, full flow diagram (sender/recipient/Q&A/governance), script dependency map, key concepts, containment chain, where-to-go-next table |

---
