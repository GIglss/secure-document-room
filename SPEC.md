# Confidant — Sovereign AI Sandbox · Project Specification (v2)

**Status:** Deployed & acceptance-tested on Azure · 2026-07-19
**Subscription:** goneset (`0f94670d-1eff-45a0-a2f8-8215eb135886`) · westeurope
**Supersedes:** v1 "sealed document room" spec (2026-07-13)

---

## 1. Problem & product

A company (a **provider** — clinic, bank, advisory firm) hands an individual **client** a private, disposable AI workspace for the length of an engagement, with a verifiable promise:

> *"Here is your document. Ask it anything — and anything about our expertise. A local AI model on an isolated machine does all the processing; nothing is ever sent to any external LLM provider. When your session ends, the machine and everything on it is destroyed."*

**What changed from v1:** the product is no longer a *sealed* room where the client never sees the file. The client can now **view and download** the document (PDF, ≤200 pages), and download it **with an AI-generated conversation-summary appendix**. The privacy pitch moved from "we hide the document" to "**the model is sovereign and the sandbox is ephemeral**."

Three scenarios, one product:

1. **Document sandbox** — provider uploads an engagement document; the client reads it and asks a local model questions with cited answers.
2. **Expertise sandbox** — no client document; the room answers from the provider's shared company knowledge base.
3. **Insight loop** — the provider gets a persistent dashboard of *high-level* client concerns (anonymized topic categories; full transcripts only when the client explicitly opts in), which survives sandbox destruction.

### Vocabulary

| Term | Meaning |
|---|---|
| **Provider / customer** | The company/clinic/bank that creates the sandbox (the "sender" in code). |
| **Client / user** | The single invited individual who logs into the sandbox (the "recipient" in code). |
| **Sandbox** | One ephemeral Azure VM running the whole app + local model for one engagement. |
| **Control plane** | The always-on, cheap Azure resources that persist across sandboxes (analytics, orchestration, gold image). |

### Trust model (the differentiator)

| Guarantee | How it's enforced |
|---|---|
| No data to any LLM provider | Inference runs on **llama.cpp + Qwen3-8B (Q4_K_M)** *inside* the sandbox VM; embeddings are local (all-MiniLM-L6-v2). Sandbox subnet blocks all outbound internet except ACME cert issuance. |
| Data exists only during the engagement | Documents, vector index, SQLite, and chat live only on the VM disk; the VM (+ NIC, IP, disk) is hard-deleted on session close or 15-min inactivity. |
| Client controls what the provider learns | Consent step at join: *anonymized topics only* (default) or *full conversation*; changeable anytime from the chat. |
| Provider insight survives destruction | Anonymized categories/topics are mirrored to Azure Table Storage in the control plane before the VM dies. |
| Weights never leave the tenant | Model weights + runtimes are pre-baked into a CMK-encrypted gold image; nothing is fetched from the public internet at runtime. |

**Local vs Azure AI Foundry — decision.** We default to local/sovereign because "the model runs on a machine we destroy" *is* the sales pitch and the strongest data-sovereignty story. Foundry (cheaper per-token, higher quality, in-tenant with limited/zero retention terms) remains a one-env-var switch (`LLM_PROVIDER=anthropic`, or any OpenAI-compatible Foundry endpoint via `LOCAL_LLM_BASE_URL`) for cost-sensitive engagements that accept policy-based guarantees instead of physical isolation.

---

## 2. Roles & user flows

**Provider (sender · JWT auth):** register/login → create room → upload PDF (per-room or company-knowledge scope) → invite client by email → monitor audit log → view the persistent insights dashboard.

**Client (recipient · session-token auth):** open invite link → email verification (6-digit code via ACS email) → accept terms **+ choose sharing mode** → read/download the document → ask the local model questions with cited answers → download the document with a conversation-summary appendix → **End Session** (or auto-timeout) → sandbox destroyed.

- **One client per sandbox** — a single invited individual.
- **Documents are viewable & downloadable** by the client (audit-logged).
- **PDF only, ≤200 pages, ≤50 MB.**

---

## 3. Application architecture

```
                          ┌──────────────── SANDBOX VM (ephemeral, isolated subnet) ────────────────┐
 Client ── HTTPS 443 ──►  │  Caddy (auto-TLS) ─► Next.js 14 frontend                                 │
                          │                     └► FastAPI backend ─► ChromaDB (room + knowledge)     │
                          │                            │              (local all-MiniLM-L6-v2)        │
                          │                            ├─► llama.cpp server (Qwen3-8B Q4_K_M, /v1)     │
                          │                            ├─► SQLite (rooms, members, docs, audit,        │
                          │                            │          qa_insights, session_activity)       │
                          │                            └─► (managed identity, via private endpoint) ──┐ │
                          └──────────────────────────────────────────────────────────────────────────┘
                                                                                                     │
        CONTROL PLANE (persistent)   Azure Table Storage: insights + sessions  ◄────────────────────┘
                                     Azure Functions: cleanup timer + provider dashboard
```

### Backend (FastAPI · Python 3.12 · SQLite · ChromaDB)
- **LLM provider** — `LLM_PROVIDER=local` against llama.cpp's OpenAI-compatible endpoint (`LOCAL_LLM_BASE_URL=http://llamacpp:8080/v1`, `LOCAL_LLM_MODEL=qwen3-8b`). `anthropic` and legacy `mlx` also supported.
- **RAG** — per-room Chroma collection + a shared `company_knowledge` collection keyed per sender id; retrieval merges both by relevance; a room with zero documents still answers from knowledge. Answers are grounded (`[N]` citation markers parsed, ungrounded answers flagged).
- **Documents** — PDF-only, ≤200 pages (pypdf count), ≤50 MB; served to both provider and client via `GET .../documents/{id}/file` (audit-logged); `?with_appendix=1` merges LLM-written "Conversation Summary" pages (reportlab + pypdf) with graceful fallback if the model is down.
- **Sharing consent** — `RoomMember.sharing_mode` ∈ {`anonymized` (default), `full`}; set at accept, changeable via `POST /api/rooms/{id}/sharing-mode`.
- **Insights pipeline** — background task classifies each answered question into one of ten categories + a 3–8-word PII-free topic label; stored in `qa_insights` (question/answer text only under `full` sharing) and mirrored to Azure Table `insights`. Failures never break Q&A.
- **Session lifecycle** — `session_activity` table tracks `logged_in_at` / `last_activity` (throttled) and mirrors to Azure Table `sessions` (keyed by `SANDBOX_ID`); `POST /api/session/close` marks `closed`. This is what the cleanup listener consumes.
- **Email** — verification codes sent via ACS (`azure-communication-email`) when configured; never returned in the API response in that mode.

### Frontend (Next.js 14 · TypeScript · Tailwind)
- **Same-origin API** — built with `NEXT_PUBLIC_API_URL="/"` so one image serves every sandbox FQDN (Next inlines the value at build time; empty strings are dropped, hence the `/` convention).
- Client room: document viewer (auth'd blob → iframe) + download buttons, cited-answer chat, "Local model · qwen3-8b — data never leaves the sandbox" badge, sharing-mode control, **End Session** (confirm → goodbye screen; `sendBeacon` on tab close).
- Provider: dashboard, room management (PDF upload with knowledge-base toggle, invites, audit log), `/insights` (categories, 14-day trend, top topics, opted-in conversations).

### Key API surface
| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/llm-config` | — | `{provider, model, base_url}` |
| `POST /api/rooms/{id}/documents` | provider | PDF upload; `scope=room\|knowledge` |
| `GET /api/rooms/{id}/documents` | provider or client | list (clients see room-scope only) |
| `GET /api/rooms/{id}/documents/{id}/file[?with_appendix=1]` | provider or client | view/download PDF (+appendix) |
| `POST /api/join/{token}/accept` | invite | accept terms + `sharing_mode` |
| `POST /api/rooms/{id}/sharing-mode` | client session | change sharing mode |
| `POST /api/rooms/{id}/qa` | provider or client | grounded, cited Q&A |
| `POST /api/session/close` | client session | end session → triggers destruction |
| `GET /api/insights[?room_id=]` | provider | aggregated analytics |

Control-plane Function endpoints: `GET /api/dashboard` (provider HTML dashboard) and `GET /api/dashboard-data` (JSON aggregate), both function-key protected.

---

## 4. Azure architecture

Two planes across three dedicated resource groups, so the whole solution sleeps/deletes without touching other workloads.

### Control plane — `confidant-core-rg` (persistent, ~€7.5/mo idle)
| Resource | Name | Purpose |
|---|---|---|
| Storage + tables | `stconfcorekcrrr5q7kmgj` (tables `insights`, `sessions`) | Analytics + session state that survive sandbox deletion. Entra-RBAC-only data plane (no keys). |
| Function app | `func-confidant-kcrrr5q7` | 1-min cleanup timer (destroys idle/closed sandboxes) + provider dashboard. |
| Key Vault + CMK + DES | `kv-conf-kcrrr5q7kmgj`, `cmk-gallery`, `des-confidant-gallery` | Customer-managed encryption for the gold image. |
| Compute Gallery | `confidant_gallery/confidant-sandbox:1.0.0` | Gold master image: llama.cpp + Qwen3-8B + app containers baked in. |
| VNet | `vnet-confidant-core` (10.20.0.0/16) | `snet-sandbox` (locked-down) + `snet-endpoints` (private endpoint). |

### Ephemeral sandboxes — `confidant-sandboxes-rg` (empty until a client is active)
- **VM:** `Standard_E4s_v6` (4 vCPU / 32 GB), **on-demand** (~€0.29/h), Ubuntu from the gold image, CMK-encrypted Premium OS disk with `deleteOption: Delete`. (Ephemeral-OS-disk variant `E4ds_v6` parameterized.) Max **2 concurrent** under the subscription's 10-vCPU regional cap.
- **Network:** NSG allows inbound **443 only** (+ SSH from deployer IP, marked removable); outbound denied except DNS to Azure + ACME 80/443. VM↔VM isolated.
- **Model runtime:** `llama-server -m qwen3-8b-q4_k_m.gguf -t 4 --mlock --ctx-size 8192` (~8 tok/s generation on 4 CPU threads).

### Landing page — `confidant-landingpage-rg`
- `goneset-swa` (goneset.com Static Web App) + `confidant-acs`. **Note:** `confidant-email` (EmailServices) cannot be moved by Azure and remains in the legacy `confidant-rg`; ACS↔email link is intact.

---

## 5. Lifecycle & operations ("the buttons")

All scripts in `infra/v2/`. Config-driven, idempotent where possible.

| Action | Command | Effect | Cost |
|---|---|---|---|
| Stand up platform | `deploy-core.sh` | Creates both v2 RGs + all control-plane resources | ~€7.5/mo idle |
| Start an engagement | `spawn-sandbox.sh <client-id>` | Spawns a sandbox from the gold image; prints its HTTPS URL | ~€0.29/h while alive |
| End an engagement | `destroy-sandbox.sh <client-id>` | Deletes VM+NIC+IP+disk (client data destroyed) | — |
| **Automatic destruction** | *(none — Function listener)* | Session close → immediate delete; else 15-min inactivity → delete | — |
| List / status | `list-sandboxes.sh`, `status.sh` | Inventory + power state | — |
| Tear everything down | `destroy-everything.sh` | Deletes both v2 RGs (typed confirmation; 90-day KV name lock warning) | €0 |

**Spawn → HTTPS-answering:** ~5–6 min (no runtime downloads; model load + ACME only). **Idle-cost lever:** dropping the private endpoint takes control-plane idle from ~€7.5 to ~€0.7/mo (data plane stays Entra-RBAC-only over TLS) — see `infra/v2/OPERATIONS.md`.

---

## 6. Verified end-to-end (2026-07-19)

Spawned a live `E4s_v6` sandbox and ran the full journey: valid ACME TLS · provider register → room → PDF upload (limits enforced) · invite → **ACS-sent** code → consent (full) · grounded Q&A with page-accurate citations in ~25 s on the local model · document download with a coherent AI-written conversation appendix · insight (`pricing`, PII-free topic) landed in the Azure Table · session close → **Function hard-deleted the VM/NIC/IP/disk within ~90 s** · insight still present on the dashboard after destruction.

---

## 7. Known limitations & open items

- **⚠ ACS email delivery unconfirmed.** ACS *accepted* the verification message but it did not arrive in the test Gmail (checked inbox/spam). Likely cause: `email_service.py` fires `begin_send` without awaiting the poller, so async delivery failures are silent. **Fix before first real client:** await `.result()` and surface status; consider a custom (branded, SPF/DKIM-aligned) sender domain for deliverability. Until fixed, treat email as best-effort.
- **CPU inference is modest** — ~8 tok/s; a full answer over a large context takes tens of seconds. GPU quota (currently 0) is the upgrade lever.
- **Two concurrent sandboxes max** — 10-vCPU regional cap; raise via quota request.
- **Provider accounts are per-sandbox** — they live in the VM's SQLite and die with it; a persistent provider control-plane/identity is the main v3 candidate.
- **Screenshots can't be prevented**; **AI answers can be wrong** (citations + disclaimers mitigate).
- **Not yet committed to git** — all v2 code/infra is in the working tree only.
- **Audit-log immutability is application-level** — Azure Confidential Ledger is a future option.

---

## 8. Pending actions on your side

| # | Action | Why it needs you |
|---|---|---|
| 1 | **Fix + verify ACS email deliverability** (or approve me doing the code fix) | Blocks real client onboarding |
| 2 | **Approve git commit** of all v2 work | Rebuild logic currently exists only on this machine |
| 3 | **GPU quota request** (optional): Portal → Subscription → Usage + quotas → NCASv3_T4 in westeurope | Bigger/faster model; subscription-owner action |
| 4 | **Custom domain + branded email** (optional): CNAME `confidant.goneset.com`, ACS domain-verification DNS records | You own the goneset.com zone |
| 5 | **Legal/terms review** of room terms + sender identity before first engagement | Brand/legal wording is yours |
