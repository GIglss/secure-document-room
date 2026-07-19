# How Does All Converge — Confidant

A new engineer's guide to how the pieces fit together. Read this before reading any individual file. For the Azure/infra side read it alongside [SAD.md](SAD.md) and [HANDOFF.md](HANDOFF.md).

---

## The core idea in one sentence

A **provider** (clinic/bank/advisory) uploads a PDF to a room and invites one **client**; the client gets a disposable sandbox VM where they read/download the document and ask a **local** AI model questions with cited answers — and when they leave, the whole VM is destroyed, while only anonymized "what did they ask about" analytics survive.

> **Terminology:** provider = "sender" in code (JWT); client = "recipient" in code (session token).

---

## Two levels: the app, and the platform around it

| Level | What runs it | Read |
|---|---|---|
| **The app** | One sandbox VM (Caddy + Next.js + FastAPI + llama.cpp + ChromaDB + SQLite) | this doc + `ARCHITECTURE.md` |
| **The platform** | Azure control plane (Functions, Table Storage, Key Vault/CMK, Compute Gallery) + per-client sandboxes | `SAD.md`, `infra/v2/OPERATIONS.md` |

Locally you can run just the app (`./start.sh`). In production the platform spawns a fresh app per engagement from a pre-baked gold image and tears it down automatically.

---

## Entry points

| Entry point | Command | Who |
|---|---|---|
| Backend API | `uv run uvicorn main:app --port 8000` (from `backend/`) | dev / VM |
| Frontend | `npm run dev` (from `frontend/`) | dev / VM |
| Both (local) | `./start.sh` | dev |
| A whole sandbox | `infra/v2/spawn-sandbox.sh <client-id>` | operator |

Inside a sandbox, Caddy fronts everything on 443 and routes `/api/*` + `/docs` to the backend, else to the frontend. The frontend is built same-origin, so the browser only ever talks to the sandbox FQDN.

---

## The full flow

### Provider flow
```
1. Provider /login → register → JWT in localStorage
2. /dashboard → create Room                         audit: room_created
3. /dashboard/rooms/{id} → upload a PDF (scope=room | knowledge)
     save to uploads/{room_id}/ → BackgroundTask: pypdf extract → ~800-char chunks
     → ChromaDB upsert into room_{id}  (or company_knowledge, keyed by sender_id)
     → UPDATE documents SET indexed=true                (PDF-only, ≤200 pages, ≤50 MB)
4. Invite client → email + UUID invite_token → invite_link      audit: member_invited
5. /insights → GET /api/insights → categories, trend, topics, opted-in conversations
```

### Client flow
```
6. Invite link → /join/{token} → GET room name, provider name, terms
7. Enter email → POST /verify → 6-digit code (emailed via ACS in prod; demo_code in dev)
8. Enter code → POST /confirm → session_token (sessionStorage)   audit: member_verified
9. Accept terms + CHOOSE SHARING MODE → POST /accept
     member.status=accepted; sharing_mode = anonymized (default) | full   audit: member_accepted
     session_activity row created (logged_in_at) → mirrored to Azure "sessions" table
10. /room/{room_id}:
     • View document  (GET .../file → auth'd blob → iframe)         audit: document_viewed
     • Download        (GET .../file)                                audit: document_downloaded
     • Download + appendix (GET .../file?with_appendix=1)  ← LLM call site 3
     • Ask questions   (POST /qa)                            ← LLM call site 1
     • Change sharing  (POST /sharing-mode)                          audit: sharing_mode_changed
     • End Session     (POST /session/close) → goodbye screen        audit: session_closed
```

### Q&A flow (fully local)
```
POST /api/rooms/{id}/qa { question, session_token }
  routes/qa.py → resolve access → rate-limit check
  rag_engine.answer_question():
    → embed question (all-MiniLM-L6-v2, local)
    → retrieve top-k from room_{id} + company_knowledge, merge/rank
    → _call_llm(): local llama.cpp (Qwen3-8B) | anthropic
    → ground: keep only cited [N] sources; set grounded flag
    → { answer, citations, grounded }
  → audit: question_asked
  → BackgroundTask: classify_question() ← LLM call site 2
       → qa_insights row (text only if sharing=full) → mirror to Azure "insights" table
  → HTTP 200 { answer, citations, grounded, question_id }
```

### Lifecycle / destruction flow (the platform)
```
While used:  session_service updates last_activity (throttled) → Azure "sessions" table
End:         POST /session/close  → status=closed
             OR 15-min inactivity → last_activity ages out
Cleanup:     Azure Function timer (every 1 min) reads "sessions"
             → closed OR idle > INACTIVITY_MINUTES → hard-delete VM + NIC + PIP + disk
             → mark row status=deleted   (insights rows remain — analytics persist)
```

---

## Script / module dependency map

```
backend/
├── main.py  → database, models, auto-migrate, all routers, startup self-heal
├── routes/
│   ├── auth · rooms · invites · documents · join · qa · session · insights · audit
│   └── (qa → rag_engine + insights_service;  documents → rag_engine + pdf_appendix)
├── services/
│   ├── document_processor.py   (pypdf)
│   ├── rag_engine.py           (chromadb, openai/anthropic — provider dispatch)
│   ├── insights_service.py     (classification + Azure Table mirror)   [azure-data-tables]
│   ├── session_service.py      (heartbeats + Azure Table mirror)       [azure-data-tables]
│   ├── pdf_appendix.py         (reportlab + pypdf)
│   ├── email_service.py        (azure-communication-email)
│   ├── audit_service.py        (sqlalchemy, append-only)
│   └── rate_limit.py           (in-memory sliding window)
frontend/
├── src/app/*/page.tsx          (pages; room + join carry the v2 client UX)
├── src/lib/api.ts              (typed fetch wrappers; same-origin build)
└── src/lib/auth.ts             (localStorage / sessionStorage tokens)
infra/v2/
├── *.bicep + *.sh              (control plane, sandbox template, the "buttons")
├── docker-compose.sandbox.yml  (the baked app stack)
└── functions/function_app.py   (cleanup timer + provider dashboard)
```

---

## Key concepts

**Room** — the central object; documents, members, audit, insights belong to it. Lifecycle `active → expired | revoked`. Only active rooms accept Q&A.

**Provider vs client (dual auth)** — providers use JWTs (localStorage); clients use TTL'd session tokens (sessionStorage, scoped to one room). `get_optional_user` handles routes that accept either.

**Ephemeral sandbox = the containment boundary (v2)** — the privacy guarantee is no longer "hide the document" but "the model is local and the VM is destroyed." The sandbox subnet blocks outbound internet except ACME; weights are baked into a CMK image. See D-117/D-118/D-120.

**Company knowledge base** — a shared ChromaDB collection keyed per sender; documents uploaded with `scope=knowledge` answer across all that provider's rooms, so a room with no documents still works.

**Consent-gated analytics** — anonymized category + PII-free topic by default; question/answer text stored only under `full` sharing. Persisted to control-plane Table Storage so it outlives the VM. See D-119.

**Three LLM call sites** — Q&A (blocking), insight classification (background, the only durable off-VM output), appendix summary (on-demand, best-effort). All local by default. See `LLM_CALL_FLOW.md`.

**Append-only audit log** — `audit_logs` has no update/delete path; source of truth for who-did-what (now includes views, downloads, session close, sharing changes).

**Self-healing indexing** — upload is non-blocking; `Document.indexed`/`index_error` track state; startup re-indexes anything left `indexed=false`.

---

## The trust chain (v2)

```
1. Model runs locally on the VM            (llama.cpp; no external LLM egress)
        ↓
2. VM subnet blocks outbound internet      (NSG; only ACME allowed)
        ↓
3. Weights never fetched at runtime        (baked into CMK gold image)
        ↓
4. Every access is logged                   (audit_service.log_event)
        ↓
5. Client agreed to terms + chose sharing   (accept gate + sharing_mode)
        ↓
6. Only anonymized analytics leave the VM   (insights mirror; text only if consented)
        ↓
7. VM + all its data destroyed at the end   (Functions cleanup timer)
```

---

## Where to go next

| Topic | File |
|-------|------|
| Product spec, trust model, open items | `SPEC.md` |
| Solution architecture (Azure + NFRs) | `SAD.md` |
| App internals, routes, services, security | `ARCHITECTURE.md` |
| Design decisions + rationale (D-117–D-123 for v2) | `DESIGN.md` |
| Exactly how the LLM is called (3 sites) | `LLM_CALL_FLOW.md` |
| Pick up the work / operate Azure | `HANDOFF.md`, `infra/v2/OPERATIONS.md` |
| API (interactive) | `/docs` (Swagger, on a running backend) |
| DB schema | `backend/models.py` |
| Env vars | `backend/.env.example` |
