# LLM Call Flow — Confidant

In v1 there was a single LLM call site. **v2 has three**, all dispatching through the same provider abstraction in `backend/services/rag_engine.py`:

1. **Q&A answer generation** — `answer_question()` (client/provider question → cited answer)
2. **Insight classification** — `services/insights_service.py` (question → category + PII-free topic label)
3. **Conversation-summary appendix** — `services/pdf_appendix.py` (Q&A history → summary prose for the PDF appendix)

The provider is selected at runtime via `LLM_PROVIDER`: **`local`** (default — llama.cpp / any OpenAI-compatible server), `anthropic`, or `mlx` (legacy alias of `local`). In production the local provider runs llama.cpp serving Qwen3-8B on the sandbox VM, so **all three call sites stay on the VM** — no document content or question text leaves the machine.

---

## Provider dispatch

**File:** `backend/services/rag_engine.py`
**Dispatch:** `_call_llm(messages)` → `_call_local()` (OpenAI SDK against `LOCAL_LLM_BASE_URL`) or `_call_anthropic()` based on `LLM_PROVIDER`.

| Provider | Client | Model source | Endpoint |
|---|---|---|---|
| `local` (default) | `openai.OpenAI` | `LOCAL_LLM_MODEL` (default `qwen3-8b`) | `LOCAL_LLM_BASE_URL` (default `http://llamacpp:8080/v1`) |
| `anthropic` | Anthropic SDK | `ANTHROPIC_MODEL` (`claude-sonnet-4-6`) | Anthropic API |
| `mlx` | → treated as `local` | legacy `MLX_*` honored if `LOCAL_*` unset | — |

The active config (provider + model, no secrets) is at `GET /api/llm-config`; the client chat shows a green **"Local model · qwen3-8b — data never leaves the sandbox"** badge when provider is `local`.

---

## Call site 1 — Q&A answer generation

```
Client/Provider ──► POST /api/rooms/{id}/qa { question, session_token? }
  │
routes/qa.py → _resolve_access()  (sender JWT OR client session; room active; member accepted)
  │  Rate-limit check (per accessor, per room) BEFORE generation — 429 if exceeded
  ▼
services/rag_engine.py → answer_question(room_id, question, sender_id)
  ├─ 1. Retrieval — embed question (all-MiniLM-L6-v2, local)
  │        query room_{id} collection AND the sender's company_knowledge rows
  │        merge + rank by distance → top-k chunks (knowledge tagged "(Company Knowledge)")
  ├─ 2. Context — "[N] Source: {doc} (p.{page})\n{chunk}" joined by "---"
  ├─ 3. _call_llm([system, user])  →  local (llama.cpp) | anthropic
  ├─ 4. _ground_answer() — keep only [N] sources actually cited; grounded flag;
  │        top source surfaced as fallback if the answer cited nothing
  └─ return { answer, citations, grounded }
  ▼
routes/qa.py → audit log "question_asked"
  → schedules BackgroundTask: classify_question(...)   ← call site 2
  ▼
HTTP 200 { answer, citations, grounded, question_id }
```

**System prompt** (unchanged intent — the AI-layer enforcement):
```
You are a secure document assistant operating inside an isolated sandbox.
Answer ONLY from the provided document excerpts.
1. Answer only from context; never invent facts.
2. Cite sources using [1], [2] notation matching the provided sources.
3. Never reproduce large verbatim passages — synthesize and paraphrase.
4. If the answer isn't in context, say so explicitly.
5. Add a brief disclaimer to verify against source documents for legal/financial decisions.
```

**What the LLM does NOT receive:** raw files, full document text, anything beyond the retrieved chunks, client identity/session token, or prior Q&A history (each call is stateless).

---

## Call site 2 — Insight classification (background, non-blocking)

```
BackgroundTask after a successful answer:
services/insights_service.py → classify_question(question)
  ├─ _call_llm([system, user])  — same provider
  │     system: "Classify into exactly one category + a 3-8 word topic label.
  │              EXCLUDE names, companies, emails, and any PII from the label."
  │     categories: pricing, legal_terms, technical_capabilities, security_compliance,
  │                 integration, support, timeline_delivery, competitive_comparison,
  │                 documentation_content, other
  ├─ parse response (code-fenced JSON | bare token | garbage → "other")
  └─ write qa_insights row (question/answer text ONLY if member.sharing_mode == "full")
       └─ mirror to Azure Table "insights" (managed identity) if configured
```

Failure here is **logged and swallowed** — it must never affect the answer the user already received. This is the only call site whose output is stored durably off-VM.

---

## Call site 3 — Conversation-summary appendix (on demand)

```
GET /api/rooms/{id}/documents/{id}/file?with_appendix=1
services/pdf_appendix.py → build_appendix(qa_history)
  ├─ _call_llm([system, user])  — summarize the client's Q&A history
  ├─ reportlab: render "Conversation Summary" pages (summary + verbatim Q list w/ excerpts)
  └─ pypdf: merge appendix onto the original PDF
Fallbacks: LLM unreachable → verbatim list only;  any failure → serve original PDF.
```

The download **never fails** — the appendix is best-effort on top of a guaranteed core action (getting the document).

---

## Provider configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `local` | `local` \| `anthropic` \| `mlx` (alias) |
| `LOCAL_LLM_BASE_URL` | `http://llamacpp:8080/v1` | OpenAI-compatible endpoint (llama.cpp/Ollama/LM Studio/MLX) |
| `LOCAL_LLM_MODEL` | `qwen3-8b` | Model alias (llama.cpp largely ignores it) |
| `LOCAL_LLM_MAX_TOKENS` | `1024` | Answer cap |
| `LOCAL_LLM_DISABLE_THINKING` | `true` | Suppress reasoning-model `<think>` channel (see below) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-sonnet-4-6` | For `anthropic` provider |

### Reasoning models (Qwen3 and similar)
Reasoning-tuned models emit a hidden `<think>` channel before answering; with a small token cap they can spend the entire budget thinking and return empty `content`. The local path disables thinking by default (`chat_template_kwargs.enable_thinking=False`), sets an explicit `max_tokens`, strips any leaked `<think>…</think>`, and falls back to the `reasoning` field if `content` is empty. For deliberate multi-hop reasoning, set `LOCAL_LLM_DISABLE_THINKING=false` and raise `LOCAL_LLM_MAX_TOKENS`. (History: D-115.)

---

## Failure modes

`routes/qa.py` wraps `answer_question()` so provider failures return a **handled** response with CORS headers and a readable `detail` (an unhandled 500 skips CORS → browser shows a generic "Failed to fetch").

| Scenario | Provider | Behavior |
|----------|----------|---------|
| No documents indexed (and no knowledge) | both | Hardcoded message; no LLM call |
| Retrieval returns nothing | both | "Couldn't find relevant information"; no LLM call |
| Local server (llama.cpp) not reachable | local | `APIConnectionError` → **HTTP 502** (CORS-safe) |
| Model not loaded | local | Server error → **HTTP 502** |
| `ANTHROPIC_API_KEY` missing/placeholder | anthropic | **HTTP 503** with actionable message |
| Anthropic rate limit / API error | anthropic | **HTTP 502** |
| Reasoning model returns empty `content` | local | Thinking disabled + strip/reasoning fallback; only fails if truly empty |
| Q&A rate limit exceeded | both | **HTTP 429** before any LLM call |
| **Insight classification error** | both | Logged + skipped; **Q&A unaffected** |
| **Appendix LLM error** | both | Falls back to verbatim list / original PDF; download succeeds |

---

## Cost

- **Local (default):** zero marginal cost — hardware only (~€0.29/h for the whole `E4s_v6` VM). All three call sites are free.
- **Anthropic (switch):** Q&A ≈ $0.003–0.005 per exchange (~1.2k input / ≤1k output tokens); classification adds a small call; appendix a larger one.

---

## Call-site summary

| # | Site | File | Trigger | Blocking? | Output persisted off-VM? |
|---|------|------|---------|-----------|--------------------------|
| 1 | Q&A answer | `rag_engine.answer_question` | `POST /qa` | Yes | No |
| 2 | Insight classification | `insights_service` | background after answer | No | Yes (Azure Table) |
| 3 | Appendix summary | `pdf_appendix` | `GET .../file?with_appendix=1` | Yes (best-effort) | No |
