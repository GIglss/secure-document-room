# Confidant — Sovereign AI Sandbox

Hand a client a private, disposable AI workspace tied to a specific document and to your own expertise. They read the document and ask a **local** AI model questions with cited answers — nothing is ever sent to an external LLM provider, and the entire workspace is **destroyed** when the engagement ends.

Built for clinics, banks, and advisory firms whose clients cannot risk their documents being fed into a public model, but who still want self-service AI answers and a read of what their clients actually care about.

> **v2 (2026-07-19):** pivoted from a *sealed* document room to a *sovereign, ephemeral sandbox*. The client now **views and downloads** the document; the privacy guarantee is the **local model on an isolated VM that is deleted at engagement end**, not hiding the file. See [SPEC.md](SPEC.md) and [SAD.md](SAD.md).

---

## How it works

```
Provider (company/clinic/bank)              Client (single invited individual)
──────────────────────────────             ───────────────────────────────────
Creates room                                Receives invite link
Uploads a PDF (or company knowledge)        Verifies email (code via ACS)
Invites the client by email                 Accepts terms + chooses sharing mode
Monitors audit log                          Reads / downloads the document
Views persistent insights dashboard  ◄────  Asks the local model questions (cited)
   (anonymized topics; full only            Downloads doc + conversation appendix
    with client consent)                     Ends session → sandbox destroyed
```

Each engagement runs on its **own Azure VM** spawned from a pre-baked gold image (llama.cpp + Qwen3-8B + the app, CMK-encrypted, zero runtime downloads). The VM sits in an egress-locked subnet, and an Azure Functions timer hard-deletes it on session close or 15 minutes of inactivity. Anonymized "what did clients ask about" analytics are mirrored to control-plane storage that **survives** the VM's destruction.

---

## Two-plane architecture

| Plane | Where | Lifecycle | Contents |
|---|---|---|---|
| **Control plane** | `confidant-core-rg` | Persistent (~€7.5/mo idle) | Table Storage (insights + sessions), Functions (cleanup timer + provider dashboard), Key Vault + CMK, Compute Gallery (gold image), VNet |
| **Sandbox** | `confidant-sandboxes-rg` | Ephemeral (~€0.29/h, one per client) | `E4s_v6` VM running Caddy + Next.js + FastAPI + llama.cpp + ChromaDB + SQLite |

Full detail in [SAD.md](SAD.md) (Solution Architecture Document) and [ARCHITECTURE.md](ARCHITECTURE.md) (app internals).

---

## Stack

| Layer | Technology |
|-------|-----------|
| Reverse proxy / TLS | Caddy 2 (automatic ACME) |
| Frontend | Next.js 14 · TypeScript · Tailwind (built same-origin) |
| Backend | Python 3.12 · FastAPI · SQLite · SQLAlchemy |
| Vector store | ChromaDB (persistent, local) · all-MiniLM-L6-v2 embeddings |
| LLM | **Local llama.cpp · Qwen3-8B Q4_K_M** (default) · Anthropic / MLX as config switches |
| Document parsing | pypdf · reportlab (appendix) |
| Cloud | Azure: Compute Gallery + CMK, Functions, Table Storage, ACS Email, Bicep IaC |
| Auth | JWT (providers) · URL-safe session tokens (clients) |

---

## Operating it (the buttons — `infra/v2/`)

```bash
./deploy-core.sh                 # stand up / update the persistent control plane
./spawn-sandbox.sh <client-id>   # start an engagement → prints the sandbox HTTPS URL
./list-sandboxes.sh              # what's currently running
./status.sh                      # power state + cost overview
./destroy-sandbox.sh <client-id> # manual teardown (auto-teardown also runs)
./destroy-everything.sh          # delete both v2 resource groups
```

Automatic destruction is handled by the Functions cleanup timer — no button needed. Provider dashboard:
`https://func-confidant-kcrrr5q7.azurewebsites.net/api/dashboard?code=<key>` (key via `az functionapp keys list -n func-confidant-kcrrr5q7 -g confidant-core-rg --query functionKeys.default -o tsv`).

Runbook and cost breakdown: [infra/v2/OPERATIONS.md](infra/v2/OPERATIONS.md).

---

## Local development

The app still runs standalone without Azure (local model or Anthropic):

```bash
cp backend/.env.example backend/.env      # set LLM_PROVIDER + model/base URL
./start.sh                                 # backend :8000 (Swagger at /docs), frontend :3000
```

Point `LOCAL_LLM_BASE_URL` at any OpenAI-compatible server (llama.cpp, Ollama, LM Studio, MLX). Without ACS configured, verification codes are returned in the API response (dev mock).

---

## User flows

### Provider
1. Register at `/login` → `/dashboard` → **Create Room**
2. **Documents** → upload a PDF (toggle **company knowledge base** to share it across all rooms)
3. **Access** → invite the client by email → copy the invite link
4. **Audit Log** → monitor in real time / export CSV
5. **Insights** (`/insights`) → categories, 14-day trend, top topics, opted-in conversations

### Client
1. Open the invite link (`/join/{token}`)
2. Enter your email → receive a 6-digit code (via ACS email in production)
3. Enter the code → review terms → **choose sharing mode** (anonymized topics only, default; or full conversation)
4. Read / download the document; ask the local model questions
5. **Download with conversation summary** for a take-away record
6. **End Session** → the sandbox (and all its data) is destroyed

---

## Key API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/llm-config` | — | Active provider + model |
| `POST` | `/api/rooms/{id}/documents` | provider | Upload PDF (`scope=room\|knowledge`) |
| `GET` | `/api/rooms/{id}/documents/{id}/file[?with_appendix=1]` | provider or client | View/download PDF (+ conversation appendix) |
| `POST` | `/api/join/{token}/accept` | invite | Accept terms + `sharing_mode` |
| `POST` | `/api/rooms/{id}/sharing-mode` | client session | Change sharing mode |
| `POST` | `/api/rooms/{id}/qa` | provider or client | Grounded, cited Q&A |
| `POST` | `/api/session/close` | client session | End session → triggers destruction |
| `GET` | `/api/insights[?room_id=]` | provider | Aggregated analytics |

Interactive Swagger UI at `/docs` when the backend is running.

---

## Documentation

| File | Contents |
|------|----------|
| [SPEC.md](SPEC.md) | Product spec (v2) — problem, trust model, architecture, buttons, verified e2e, open items |
| [SAD.md](SAD.md) | Solution Architecture Document — overview, topology, data flow, UX/functional, NFRs |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Application internals — layers, routes, services, data stores |
| [DESIGN.md](DESIGN.md) | Engineering + product decisions with rationale (incl. v2 decisions D-117–D-123) |
| [LLM_CALL_FLOW.md](LLM_CALL_FLOW.md) | The three LLM call sites — Q&A, insight classification, appendix summary |
| [HOW_DOES_ALL_CONVERGE.md](HOW_DOES_ALL_CONVERGE.md) | New-engineer orientation: entry points, full flow, key concepts |
| [HANDOFF.md](HANDOFF.md) | Pickup brief for the next engineer/agent |
| [infra/v2/OPERATIONS.md](infra/v2/OPERATIONS.md) | Azure runbook + cost table |

---

## Known limitations

- **⚠ ACS email deliverability unconfirmed** — see [SPEC.md §7](SPEC.md) / D-122; fix before first real client.
- **CPU inference is modest** (~8 tok/s) — GPU quota is the upgrade lever.
- **Max 2 concurrent sandboxes** under the 10-vCPU regional cap.
- **Provider accounts are per-sandbox** (live in the VM's SQLite; a persistent control plane is the main v3 candidate).
- **Screenshots can't be prevented**; **AI answers can be wrong** (citations + disclaimers mitigate).
