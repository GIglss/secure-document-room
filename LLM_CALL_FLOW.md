# LLM Call Flow — Secure Document Room

There is exactly one LLM call site in the codebase. It lives in `backend/services/rag_engine.py` inside `answer_question()`. All Q&A requests — from both senders and recipients — flow through it.

The provider is selected at runtime via `LLM_PROVIDER` in `.env`. Supported values: `anthropic` (default) and `mlx` (local MLX model via `mlx_lm.server`).

---

## Call location

**File:** `backend/services/rag_engine.py`  
**Function:** `answer_question(room_id: str, question: str) -> dict`  
**Max tokens:** 1024 (Anthropic) / no limit enforced (Ollama)  
**Dispatch:** `_call_llm()` → `_call_anthropic()` or `_call_ollama()` based on `LLM_PROVIDER`

---

## Full call flow

```
Browser (recipient or sender)
  │
  │  POST /api/rooms/{room_id}/qa
  │  Body: { question, session_token? }
  │
  ▼
routes/qa.py → _resolve_access()
  │  Validates: sender JWT OR recipient session_token
  │  Verifies: room is active, member status = "accepted"
  │
  ▼
services/rag_engine.py → answer_question(room_id, question)
  │
  ├─ 1. Retrieval
  │     ChromaDB collection: room_{room_id}
  │     Query: question text → DefaultEmbeddingFunction (all-MiniLM-L6-v2, local)
  │     Returns: top-5 chunks by cosine similarity
  │     Each chunk carries metadata: doc_name, chunk_index, page_num/section/sheet_name
  │
  ├─ 2. Context construction
  │     Each chunk formatted as:
  │       "[N] Source: {doc_name} (p.{page_ref})\n{chunk_text}"
  │     Chunks joined with "---" separator
  │     Citations list built from metadata (document_name, page_ref, excerpt[:200])
  │
  ├─ 3. LLM dispatch → _call_llm(user_message)
  │
  │     LLM_PROVIDER=anthropic (default)          LLM_PROVIDER=mlx
  │     ──────────────────────────────────         ──────────────────────────────
  │     _call_anthropic(user_message)              _call_mlx(user_message)
  │       Anthropic SDK                              openai.OpenAI client
  │       model: ANTHROPIC_MODEL                     base_url: MLX_BASE_URL
  │               (default: claude-sonnet-4-6)               (default: http://localhost:8080/v1)
  │       max_tokens: 1024                           model: MLX_MODEL
  │       system= SYSTEM_PROMPT                              (default: mlx-community/Qwen3.5-4B-MLX-4bit)
  │       messages: [{role:user, content:…}]         api_key: "not-required"
  │       (placeholder "your-" key →                 max_tokens: MLX_MAX_TOKENS (default 1024)
  │        ValueError, actionable msg)               extra_body: enable_thinking=False
  │       → message.content[0].text                          (MLX_DISABLE_THINKING, default true)
  │                                                   messages: [system, user], stream: false
  │                                                 → _strip_think(choices[0].message.content)
  │                                                   (fallback to .reasoning if content empty)
  │
  └─ 4. Return
        answer_text (raw model output)
  │
  ├─ 5. Grounding & citation verification → _ground_answer()
  │     - If answer contains the "cannot answer from context" phrase:
  │         → { answer, citations: [], grounded: false }
  │     - Else parse [N] markers actually used in the answer:
  │         → return only those retrieved sources, each with its marker `number`
  │         → if the answer cited nothing, surface the top source as a fallback
  │         → { answer, citations: [...referenced], grounded: true }
  │
  └─ Return { answer, citations, grounded }
  │
  ▼
routes/qa.py
  │  Rate-limit check (per accessor, per room) BEFORE generation — 429 if exceeded
  │  Logs to audit_logs: event_type="question_asked"
  │  event_data includes: question, answer_preview[:200], citation_count, grounded
  │
  ▼
HTTP 200 → { answer, citations, grounded, question_id }
```

**Note on embeddings:** Both providers use the same ChromaDB `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, runs locally). Switching LLM provider does not change retrieval behavior.

---

## System prompt

The system prompt is the primary enforcement mechanism at the AI layer:

```
You are a secure document assistant operating inside a sealed document room.
Your role is to answer questions based ONLY on the provided document excerpts.

Rules you must follow:
1. Answer only from the provided context. Never invent or extrapolate facts.
2. Cite sources using [1], [2], etc. notation matching the provided sources.
3. Never reproduce large verbatim passages. Synthesize and paraphrase.
4. If the answer is not in the context, say: "The documents in this room do not
   contain information to answer that question."
5. Add a brief disclaimer that answers should be verified against source documents
   for legal or financial decisions.
```

**Why this matters:** Rules 3 and 4 are the containment rules. Rule 3 prevents bulk text extraction through Q&A. Rule 4 prevents hallucination on legal/financial content — a hallucinated clause reference acted on by a lawyer is worse than no answer.

---

## User message structure

```
Context from room documents:

[1] Source: AcquisitionAgreement.pdf (p.12)
{chunk_text_1}

---

[2] Source: FinancialModel.xlsx (sheet: P&L)
{chunk_text_2}

---

... (up to 5 chunks)

Question: {question}

Please answer based only on the above context, with appropriate citations.
```

---

## What the LLM does NOT receive

- Raw document files
- Full document text
- Any content outside the retrieved top-5 chunks
- Recipient identity or session token
- Any prior Q&A history (each call is stateless)

---

## Provider configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `mlx` |
| `ANTHROPIC_API_KEY` | — | Required when provider=anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Any Anthropic model ID |
| `MLX_BASE_URL` | `http://localhost:8080/v1` | MLX server OpenAI-compatible endpoint |
| `MLX_MODEL` | `mlx-community/Qwen3.5-4B-MLX-4bit` | Any HuggingFace MLX model ID |
| `MLX_MAX_TOKENS` | `1024` | Max tokens for the generated answer |
| `MLX_DISABLE_THINKING` | `true` | Suppress reasoning-model `<think>` channel (see below) |

The active config (provider + model, no keys) is exposed at `GET /api/llm-config` and displayed as a badge in the Q&A interface header (green "Local MLX · Qwen3.5-4B-MLX-4bit" vs blue "Cloud · claude-sonnet-4-6").

### Reasoning models (Qwen3 and similar)

Reasoning-tuned models emit a hidden `<think>` / `reasoning` channel before the answer. With `mlx_lm.server`'s default 512-token cap, Qwen3 spent the **entire budget thinking** (`finish_reason: length`) and returned an **empty `content`** — surfacing as "Unable to generate answer."

`_call_mlx()` mitigates this for the extraction-style RAG task:
1. **Disables thinking** via `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (`MLX_DISABLE_THINKING=true`), so the model answers directly into `content`.
2. **Sets `max_tokens`** explicitly (`MLX_MAX_TOKENS`, default 1024) so a full answer isn't truncated.
3. **`_strip_think()`** removes any leaked `<think>…</think>` block, and if `content` is still empty it falls back to the `reasoning` channel.

To keep a model's reasoning enabled, set `MLX_DISABLE_THINKING=false` and raise `MLX_MAX_TOKENS` (e.g. 2048+) so thinking plus the answer both fit.

### Using MLX

The MLX server (`mlx_lm.server`) exposes an OpenAI-compatible API. Start it from the `local-ai` repo:

```bash
# Start the inference server (downloads model on first run)
cd /path/to/local-ai/mlx
./start.sh                              # uses Qwen3.5-4B-MLX-4bit by default
./start.sh --model mlx-community/Qwen3-14B-4bit   # larger model

# Then set in backend/.env
LLM_PROVIDER=mlx
MLX_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
```

Restart the backend. The Q&A interface will show a green **"Local MLX · Qwen3.5-4B-MLX-4bit"** badge.

---

## Failure modes

`routes/qa.py` wraps `answer_question()` so provider failures return a **handled** response that carries CORS headers and a readable `detail` — without the wrapper, an unhandled 500 skips CORS headers and the browser shows a generic "Failed to fetch" instead of the real reason.

| Scenario | Provider | Behavior |
|----------|----------|---------|
| No documents indexed in room | both | Returns hardcoded message; no LLM call made |
| ChromaDB returns no results | both | Returns "couldn't find relevant information"; no LLM call made |
| `ANTHROPIC_API_KEY` missing / placeholder (`your-…`) | anthropic | `ValueError` → **HTTP 503** with actionable message ("set a real key, or `LLM_PROVIDER=mlx`") |
| Anthropic rate limit / API error | anthropic | **HTTP 502** `AI provider error: …` (CORS-safe) |
| MLX server not running | mlx | `openai.APIConnectionError` → **HTTP 502** — run `./start.sh` in `local-ai/mlx` |
| Model not loaded in MLX server | mlx | Server error → **HTTP 502** — restart server with correct `--model` |
| Reasoning model returns empty `content` | mlx | Thinking disabled + `_strip_think()`/reasoning fallback; only "Unable to generate answer." if truly empty |
| Q&A rate limit exceeded | both | **HTTP 429** before any LLM call |

---

## Token budget (Anthropic provider)

Each call sends approximately:
- System prompt: ~120 tokens
- Context (5 chunks × ~200 tokens each): ~1,000 tokens
- Question: ~30–100 tokens
- **Input total: ~1,150–1,220 tokens per call**
- Output cap: 1,024 tokens

At current Anthropic pricing for `claude-sonnet-4-6`, this is approximately $0.003–0.005 per Q&A exchange. With Ollama, cost is zero (hardware only).

---

## Future LLM call sites (post-MVP)

| Feature | Likely location | Notes |
|---------|----------------|-------|
| Visible watermark text generation | `services/watermark.py` | Would generate recipient-specific watermark strings |
| Auto-redaction suggestions | `services/redaction.py` | Would highlight sensitive passages before sender finalizes room |
| Question topic classification | `routes/qa.py` | Would enforce sender-defined topic restrictions |
