# How Does All Converge — Secure Document Room

A new engineer's guide to how the pieces fit together. Read this before reading any individual file.

---

## The core idea in one sentence

A sender uploads documents to a sealed room; a recipient joins via an invite link, accepts legal terms, and asks natural-language questions; an AI answers from the documents — without either party ever seeing raw file content.

---

## The two entry points

Everything starts from one of two places:

| Entry point | Command | Who runs it |
|-------------|---------|------------|
| Backend API | `uv run uvicorn main:app --port 8000` (from `backend/`) | Developer / server |
| Frontend app | `npm run dev` (from `frontend/`) | Developer / server |

Both together: `./start.sh` from the project root.

The frontend proxies all `/api/*` requests to the backend via `next.config.ts` rewrites — so the browser only ever talks to `localhost:3000`.

---

## The full flow diagram

### Sender flow

```
1. Sender visits /login → registers → JWT stored in localStorage

2. Sender opens /dashboard → creates a Room
   backend: INSERT into rooms → audit: room_created

3. Sender opens /dashboard/rooms/{id} → uploads a PDF
   backend: saves file to uploads/{room_id}/
           → BackgroundTask: extract text (pypdf)
           → chunk into ~800-char segments
           → ChromaDB: upsert chunks into collection room_{id}
           → UPDATE documents SET indexed=true, chunks_count=N

4. Sender invites recipient → email + UUID invite_token generated
   → invite_link = http://localhost:3000/join/{token}
   audit: member_invited
```

### Recipient flow

```
5. Recipient clicks invite link → /join/{token}
   GET /api/join/{token} → room name, sender name, terms text

6. Recipient enters email →
   POST /api/join/{token}/verify
   → validates email matches invite
   → generates 6-digit code (returned in demo_code field, MVP only)

7. Recipient enters code →
   POST /api/join/{token}/confirm
   → validates code → creates session_token (UUID)
   → stores in sessionStorage
   audit: member_verified

8. Recipient accepts terms checkbox →
   POST /api/join/{token}/accept
   → member.status = "accepted"
   → redirect to /room/{room_id}
   audit: member_accepted
```

### Q&A flow

```
9. Recipient types question in /room/{room_id}
   POST /api/rooms/{id}/qa { question, session_token }

   backend/routes/qa.py:
     → validates session_token → room_members lookup
     → calls services/rag_engine.answer_question(room_id, question)

   services/rag_engine.py:
     → ChromaDB query: top-5 chunks by cosine similarity
     → builds context string with [1]..[5] citations
     → Anthropic API: claude-sonnet-4-6 with containment system prompt
     → returns { answer, citations }

   → logs to audit_logs: event_type="question_asked"
   → HTTP 200: { answer, citations, question_id }

   frontend: renders answer in chat + citations in right panel
```

### Sender governance flow

```
10. Sender opens Audit Log tab → GET /api/rooms/{id}/audit
    → all events newest-first
    → "Export CSV" → GET /api/rooms/{id}/audit/export
    → StreamingResponse CSV download

11. Sender clicks "Revoke" on a member
    → member.status = "revoked"
    → next Q&A attempt with that session_token → 403
    audit: member_revoked

12. Sender clicks "Close Room"
    → PATCH /api/rooms/{id} { status: "revoked" }
    → all Q&A attempts → 403
    audit: room_revoked
```

---

## Script dependency map

```
backend/
├── main.py
│   ├── database.py          (engine, SessionLocal, Base)
│   ├── models.py            (User, Room, Document, RoomMember, AuditLog)
│   ├── routes/auth.py       → auth.py (hash_password, get_current_user)
│   ├── routes/rooms.py      → auth.py, services/audit_service.py
│   ├── routes/documents.py  → auth.py, services/document_processor.py,
│   │                           services/rag_engine.py, services/audit_service.py
│   ├── routes/invites.py    → auth.py, services/audit_service.py
│   ├── routes/join.py       → services/audit_service.py
│   ├── routes/qa.py         → auth.py, services/rag_engine.py,
│   │                           services/audit_service.py
│   └── routes/audit.py      → auth.py, services/audit_service.py
│
├── services/document_processor.py   (pypdf, python-docx, openpyxl)
├── services/rag_engine.py           (chromadb, anthropic)
└── services/audit_service.py        (sqlalchemy)

frontend/
├── src/app/*/page.tsx        (all pages import from lib/api.ts, lib/auth.ts)
├── src/lib/api.ts            (fetch wrappers for every backend endpoint)
└── src/lib/auth.ts           (localStorage/sessionStorage token management)
```

---

## Key concepts

**Room** — the central object. Everything else (documents, members, audit events) belongs to a room. A room has a lifecycle: `active → expired | revoked | archived`. Only active rooms accept Q&A.

**Sealed environment invariant** — raw document content never leaves the backend. The only output from a room is synthesized AI answers with citations. This is enforced at two layers: (1) no download endpoint exists, (2) the LLM system prompt forbids verbatim reproduction.

**Dual auth model** — the backend has two identity types. Senders authenticate with long-lived JWTs (24h, stored in localStorage). Recipients authenticate with single-use session tokens (UUID, stored in sessionStorage, scoped to one room). The `get_optional_user` FastAPI dependency handles Q&A routes that accept either.

**Append-only audit log** — `audit_logs` has no update or delete path anywhere in the codebase. It is the source of truth for "who did what, when." Every state-changing operation calls `services/audit_service.log_event()`.

**ChromaDB collection per room** — each room's document chunks are stored in an isolated ChromaDB collection (`room_{uuid}`). This ensures retrieval for room A cannot surface content from room B, and deleting a room's data is a single `client.delete_collection()` call.

**Background indexing** — document upload is non-blocking. The file is saved and the API returns immediately. ChromaDB indexing happens in a FastAPI `BackgroundTasks` job. The `Document.indexed` flag tracks whether a document is queryable yet.

---

## The containment chain

The product's value rests on this chain. If any link breaks, the containment claim weakens:

```
1. File never served as download           (no static file route)
         ↓
2. Recipient sees no document browser      (frontend: Q&A only)
         ↓
3. LLM retrieves only top-5 chunks        (ChromaDB top-k query)
         ↓
4. LLM synthesizes, does not quote        (system prompt rule 3)
         ↓
5. Every answer is logged                  (audit_service.log_event)
         ↓
6. Recipient agreed to terms              (member.status = "accepted" gate)
         ↓
7. Sender can revoke at any time          (member.status = "revoked")
```

---

## Where to go next

| Topic | File |
|-------|------|
| All design decisions and their rationale | `DESIGN.md` |
| System architecture and upgrade paths | `ARCHITECTURE.md` |
| Exactly how the LLM is called | `LLM_CALL_FLOW.md` |
| API endpoints (interactive) | `http://localhost:8000/docs` (Swagger UI, auto-generated) |
| Database schema | `backend/models.py` |
| Environment variables | `backend/.env.example` |
| How to run locally | `start.sh` |
