# Secure Document Room

A sealed, AI-powered document room for two-party sensitive document sharing. Upload confidential files, invite an external counterparty, and let them conduct AI-powered Q&A — without raw document content ever leaving the controlled environment.

Built for M&A due diligence, legal document review, and any context where both sides need AI-assisted access to sensitive documents but neither can risk feeding them into a public model.

> **Why now:** The February 2026 federal privilege-waiver ruling established that feeding privileged legal documents into a public AI model can constitute a disclosure sufficient to waive attorney-client privilege. This is a hard regulatory forcing function, not a reputational one.

---

## How it works

```
Sender                                    Recipient
──────                                    ─────────
Creates room                              Receives invite link
Uploads documents (PDF/DOCX/XLSX)         Verifies email
Invites recipient by email                Accepts room terms
                                          Asks questions in plain language
Monitors audit log in real time  ←────→  Gets cited AI answers
Revokes access at any time                (no raw document access)
Exports immutable audit trail
```

The AI engine lives **inside** the room. Recipients never see raw document text — only synthesized answers with citations. Every question asked is logged in an append-only audit trail visible to the sender.

---

## Features

- **Sealed environment** — no download buttons, no document viewer, no raw content served to the browser
- **AI Q&A with citations** — answers grounded in retrieved document passages with source and page references
- **Two-step recipient onboarding** — email verification + explicit terms acceptance before room entry
- **Immutable audit log** — every access, question, and governance action logged; exportable as CSV
- **Room governance** — expiry dates, per-recipient revocation, room closure
- **Dual LLM support** — Anthropic cloud API or local MLX model (`mlx_lm.server`)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 · FastAPI · SQLite · SQLAlchemy |
| Vector store | ChromaDB (persistent, local) · all-MiniLM-L6-v2 embeddings |
| LLM | Anthropic `claude-sonnet-4-6` **or** local MLX via `mlx_lm.server` |
| Document parsing | pypdf · python-docx · openpyxl |
| Frontend | Next.js 14 · TypeScript · Tailwind CSS |
| Auth | JWT (senders) · UUID session tokens (recipients) |

---

## Quickstart

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- An Anthropic API key **or** a running MLX inference server

### 1. Clone and configure

```bash
git clone https://github.com/GIglss/secure-document-room
cd secure-document-room

cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY (or configure MLX below)
```

### 2. Run

```bash
./start.sh
```

Opens:
- **Backend API** → `http://localhost:8000` (Swagger docs at `/docs`)
- **Frontend** → `http://localhost:3000`

---

## LLM providers

### Anthropic (default)

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6   # optional override
```

### Local MLX model

Uses [`mlx_lm.server`](https://github.com/ml-explore/mlx-lm) — exposes an OpenAI-compatible API on port 8080. Runs entirely on-device (Apple Silicon).

```bash
# Start the inference server (downloads model on first run, ~2-8 GB)
cd /path/to/local-ai/mlx
./start.sh                                          # Qwen3.5-4B-MLX-4bit (default)
./start.sh --model mlx-community/Qwen3-14B-4bit    # larger model
```

```env
# backend/.env
LLM_PROVIDER=mlx
MLX_BASE_URL=http://localhost:8080/v1
MLX_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
```

The Q&A interface shows a green **"Local MLX · \<model\>"** badge when running on-device.

> **Note on embeddings:** Both providers use ChromaDB's local `all-MiniLM-L6-v2` for retrieval. The LLM provider only affects answer generation — switching providers does not change what gets retrieved.

---

## User flows

### Sender

1. Register at `/login` → create account
2. Dashboard (`/dashboard`) → **Create New Room**
3. Room detail → **Documents** tab → upload PDF, DOCX, or XLSX files
4. **Access** tab → enter recipient email → **Send Invite** → copy link
5. **Audit Log** tab → monitor questions in real time or export CSV

### Recipient

1. Open the invite link (`/join/{token}`)
2. Enter your email address → receive a 6-digit verification code
3. Enter the code → review and accept room terms
4. Ask questions in the chat interface → receive cited AI answers

> **Demo note:** In development the verification code is returned directly in the API response (shown on-screen). Wire in SMTP/SendGrid before any production use.

---

## Project structure

```
secure-document-room/
├── backend/
│   ├── main.py                     # FastAPI app, CORS, startup
│   ├── models.py                   # SQLAlchemy ORM models
│   ├── schemas.py                  # Pydantic request/response types
│   ├── auth.py                     # JWT + bcrypt
│   ├── database.py                 # SQLite engine + session factory
│   ├── routes/
│   │   ├── auth.py                 # /api/auth/*
│   │   ├── rooms.py                # /api/rooms/*
│   │   ├── documents.py            # /api/rooms/{id}/documents
│   │   ├── invites.py              # /api/rooms/{id}/invites + members
│   │   ├── join.py                 # /api/join/{token}/* (recipient flow)
│   │   ├── qa.py                   # /api/rooms/{id}/qa
│   │   └── audit.py                # /api/rooms/{id}/audit + export
│   └── services/
│       ├── document_processor.py   # PDF/DOCX/XLSX extraction + chunking
│       ├── rag_engine.py           # ChromaDB retrieval + LLM dispatch
│       └── audit_service.py        # Append-only event logging
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx            # Landing page
│       │   ├── login/              # Sender auth
│       │   ├── dashboard/          # Room list + management
│       │   ├── join/[token]/       # Recipient onboarding flow
│       │   └── room/[roomId]/      # Q&A interface
│       └── lib/
│           ├── api.ts              # Typed API client
│           └── auth.ts             # Token storage helpers
├── start.sh                        # Launch both servers
├── ARCHITECTURE.md                 # System architecture + upgrade paths
├── DESIGN.md                       # Engineering + product decisions
├── LLM_CALL_FLOW.md                # Full LLM call trace + provider config
└── HOW_DOES_ALL_CONVERGE.md        # New engineer orientation guide
```

---

## API reference

Interactive Swagger UI available at `http://localhost:8000/docs` when the backend is running.

Key endpoints:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | — | Create sender account |
| `POST` | `/api/auth/login` | — | Sign in, receive JWT |
| `GET` | `/api/rooms` | JWT | List sender's rooms |
| `POST` | `/api/rooms` | JWT | Create room |
| `POST` | `/api/rooms/{id}/documents` | JWT | Upload document (triggers background indexing) |
| `POST` | `/api/rooms/{id}/invites` | JWT | Invite recipient, get invite link |
| `DELETE` | `/api/rooms/{id}/members/{mid}` | JWT | Revoke recipient access |
| `GET` | `/api/join/{token}` | — | Recipient: get room info + terms |
| `POST` | `/api/join/{token}/verify` | — | Recipient: submit email |
| `POST` | `/api/join/{token}/confirm` | — | Recipient: submit verification code |
| `POST` | `/api/join/{token}/accept` | — | Recipient: accept terms → session token |
| `POST` | `/api/rooms/{id}/qa` | JWT or session | Ask a question |
| `GET` | `/api/rooms/{id}/audit` | JWT | Fetch audit log |
| `GET` | `/api/rooms/{id}/audit/export` | JWT | Download audit CSV |
| `GET` | `/api/llm-config` | — | Active LLM provider + model (no secrets) |

---

## Configuration reference

All config lives in `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-key-...` | JWT signing key — **change in production** |
| `DATABASE_URL` | `sqlite:///./secure_room.db` | SQLAlchemy connection string |
| `UPLOAD_DIR` | `./uploads` | Where uploaded files are stored |
| `CHROMA_DIR` | `./data/chroma` | ChromaDB persistence directory |
| `FRONTEND_URL` | `http://localhost:3000` | Used for CORS and invite link generation |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `mlx` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Any Anthropic model ID |
| `MLX_BASE_URL` | `http://localhost:8080/v1` | MLX server endpoint |
| `MLX_MODEL` | `mlx-community/Qwen3.5-4B-MLX-4bit` | Any HuggingFace MLX model ID |

---

## Known limitations

These are intentional trade-offs documented in the product brief, not bugs:

- **Screenshots cannot be prevented.** The product's defense is accountability (audit trail, legal terms, watermarking post-MVP) and meaningful friction, not a cryptographic guarantee against all extraction.
- **Cloud LLM sees document chunks.** When using Anthropic, document passages are sent to Anthropic's API. Enterprise zero-training DPAs reduce risk. Use the MLX provider for fully on-device inference.
- **AI answers can be wrong.** RAG is not infallible. Answers include disclaimers and citations; material facts should be verified against source documents before acting on them.
- **Email verification is mocked in dev.** The 6-digit code is returned in the API response. Wire in real email before any non-demo use.

---

## Documentation

| File | Contents |
|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System layers, data stores, security model, production upgrade paths |
| [DESIGN.md](DESIGN.md) | Engineering and product decisions with rationale |
| [LLM_CALL_FLOW.md](LLM_CALL_FLOW.md) | Full LLM call trace, system prompt, provider config, failure modes |
| [HOW_DOES_ALL_CONVERGE.md](HOW_DOES_ALL_CONVERGE.md) | New engineer orientation: entry points, full flow diagram, key concepts |
