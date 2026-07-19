# Documentation Update Trace — v2: Sovereign Ephemeral Sandbox on Azure

> Generated July 19, 2026.
> Purpose: Records the v2 pivot from a "sealed document room" to a **sovereign, ephemeral, per-client AI sandbox on Azure**, deployed and acceptance-tested end-to-end. Product change: documents are now viewable/downloadable by the client; the privacy guarantee moved to a local model on an isolated VM that is destroyed at engagement end.
> Status: **APPLIED & DEPLOYED** (Azure, verified live) — July 19, 2026. **Not yet committed** — commit deferred per request.

---

## What Changed in the Codebase

### Product pivot (app)
- **PDF-only uploads, ≤200 pages, ≤50 MB** enforced (`routes/documents.py`, pypdf page count; frontend `accept=".pdf"` + copy).
- **Document view/download for the client** — new `GET /api/rooms/{id}/documents/{id}/file` (dual auth: provider JWT or client session), audit-logged (`document_viewed`/`document_downloaded`). Frontend viewer (auth'd blob → iframe) + download buttons. Sealed-room copy removed across landing/join/room/layout + backend `TERMS_TEXT`.
- **Download-with-appendix** — `?with_appendix=1` merges an LLM-written "Conversation Summary" (new `services/pdf_appendix.py`, reportlab + pypdf) with graceful fallback if the model is down. Added `reportlab` dep.
- **Session lifecycle** — new `session_activity` table + `services/session_service.py`; `logged_in_at`/`last_activity` (throttled) mirrored to Azure Table `sessions` keyed by `SANDBOX_ID`; new `POST /api/session/close` (`routes/session.py`); frontend **End Session** button + `sendBeacon` on `pagehide`.
- **Sharing consent kept** — `RoomMember.sharing_mode` (`anonymized` default | `full`); `POST /api/rooms/{id}/sharing-mode`.
- **Insights** — `services/insights_service.py` classifies each answered question into 10 categories + PII-free topic label; `qa_insights` table stores text only under `full` sharing; mirrored to Azure Table `insights`. Aggregated by `GET /api/insights` (`routes/insights.py`).
- **Local provider generalized** — `LLM_PROVIDER=local` against llama.cpp OpenAI-compatible endpoint; `LOCAL_LLM_MODEL=qwen3-8b`; `mlx` kept as alias.
- **Email** — `services/email_service.py` sends verification codes via ACS when configured (⚠ open item: `begin_send` poller not awaited → silent async failures).
- **Frontend base-URL fix** — `src/lib/api.ts` uses `?? "http://localhost:8000"` + trailing-slash strip; built with `NEXT_PUBLIC_API_URL="/"` for same-origin (Next 14 drops empty-string env inlining).

### Infrastructure (all new, under `infra/v2/`)
- **`core.bicep` / `main.bicep`** — control plane in `confidant-core-rg`: storage (tables `insights`+`sessions`, Entra-RBAC-only), VNet + locked-down `snet-sandbox` NSG, storage private endpoint, Key Vault + CMK + Disk Encryption Set, Compute Gallery + image definition, Function app shell with scoped RBAC (VM/Network Contributor on sandboxes RG, Table Data Contributor on core storage).
- **`sandbox.bicep` (+ rbac/table-role modules)** — per-client `E4s_v6` VM from gold image, CMK OS disk `deleteOption: Delete`, system MI, cloud-init `runtime.env` injection (PUBLIC_HOST/SANDBOX_ID/SECRET_KEY/ACS_*), no secrets baked.
- **Gold image** — gallery version `confidant_gallery/confidant-sandbox:1.0.0`, CMK-encrypted: llama.cpp + Qwen3-8B Q4_K_M (sha-verified) + 4 app docker images + `confidant.service` systemd unit baked in; zero runtime downloads. `docker-compose.sandbox.yml`.
- **Functions control plane** (`infra/v2/functions/`) — `function_app.py`: 1-min `sandbox_cleanup` timer (closed → immediate delete; active + >`INACTIVITY_MINUTES` idle → hard-delete VM/NIC/PIP/disk, idempotent, never throws), `dashboard_data` JSON aggregate, self-contained `dashboard` HTML page.
- **Buttons** — `deploy-core.sh`, `spawn-sandbox.sh`, `destroy-sandbox.sh`, `list-sandboxes.sh`, `status.sh`, `destroy-everything.sh`, `lib.sh`, `OPERATIONS.md`.
- **Landing page** — `goneset-swa` + `confidant-acs` moved to `confidant-landingpage-rg`; `confidant-email` (unmovable) left in `confidant-rg`.

### Azure state (deployed, westeurope, sub goneset)
Control plane live in `confidant-core-rg`; gold image `1.0.0` Succeeded (CMK); full e2e verified including automatic sandbox destruction ~90s after session close, with insights persisting. Idle cost ~€7.5/mo; sandbox ~€0.29/h.

## Documentation Changes

| File | What was updated |
|------|-----------------|
| `SPEC.md` | Rewritten to v2 (sovereign ephemeral sandbox, two-plane Azure architecture, buttons, verified e2e, open items) |
| `SAD.md` | Created — Solution Architecture Document (overview, technical architecture, data flow, UX/functional, NFRs) |
| `HANDOFF.md` | Created — pickup brief for the next engineer/agent |
| `README.md` | Rewritten to v2 — sovereign sandbox framing, two-plane table, buttons, local-model stack, v2 endpoints/flows |
| `ARCHITECTURE.md` | Rewritten to v2 app internals — runtime topology, new routes (session/insights) + services (insights/session/pdf_appendix/email), company_knowledge + Azure-Table stores, v2 security model (containment = ephemeral VM) |
| `DESIGN.md` | Added v2 decisions D-117–D-123; marked D-107 superseded by D-120; updated open-decisions statuses (OD-1 resolved, name = Confidant) |
| `LLM_CALL_FLOW.md` | Rewritten for **three** call sites (Q&A, insight classification, appendix summary) + local llama.cpp provider dispatch; failure modes and cost updated |
| `HOW_DOES_ALL_CONVERGE.md` | Rewritten to v2 — app-vs-platform framing, provider/client flows incl. view/download + consent + End Session, lifecycle/destruction flow, v2 trust chain |
| `DOCS_UPDATE_TRACE.md` | This entry |

### Coding plan & next steps (as of this entry)
1. **Fix ACS email deliverability** (await `begin_send` poller, surface status; consider branded sender domain) — blocks first real client.
2. **Commit all v2 work** to git (currently working-tree only).
3. Optional: GPU quota request (faster/bigger model), custom domain + branded email, persistent provider identity (v3), close ACME egress after boot.

---

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
