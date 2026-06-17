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
