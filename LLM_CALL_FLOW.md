# LLM Call Flow — Secure Document Room

There is exactly one LLM call site in the codebase. It lives in `backend/services/rag_engine.py` inside `answer_question()`. All Q&A requests — from both senders and recipients — flow through it.

The provider is selected at runtime via `LLM_PROVIDER` in `.env`. Supported values: `anthropic` (default) and `ollama` (local model).

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
  │     LLM_PROVIDER=anthropic (default)          LLM_PROVIDER=ollama
  │     ──────────────────────────────────         ──────────────────────────────
  │     _call_anthropic(user_message)              _call_ollama(user_message)
  │       Anthropic SDK                              httpx.post (sync, timeout=120s)
  │       model: ANTHROPIC_MODEL                     POST {OLLAMA_BASE_URL}/api/chat
  │               (default: claude-sonnet-4-6)       model: OLLAMA_MODEL
  │       max_tokens: 1024                                   (default: llama3.2)
  │       system= SYSTEM_PROMPT                      messages: [system, user]
  │       messages: [{role:user, content:…}]         stream: false
  │       → message.content[0].text                → data["message"]["content"]
  │
  └─ 4. Return
        { answer: str, citations: list[Citation] }
  │
  ▼
routes/qa.py
  │  Logs to audit_logs: event_type="question_asked"
  │  event_data includes: question, answer_preview[:200], citation_count
  │
  ▼
HTTP 200 → { answer, citations, question_id }
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
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `ollama` |
| `ANTHROPIC_API_KEY` | — | Required when provider=anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Any Anthropic model ID |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Any model pulled in Ollama |

The active config (provider + model, no keys) is exposed at `GET /api/llm-config` and displayed as a badge in the Q&A interface header.

### Using Ollama

```bash
# 1. Install Ollama: https://ollama.com
# 2. Pull a model
ollama pull llama3.2        # fast, good general performance
ollama pull mistral         # strong instruction-following
ollama pull llama3.1:8b     # larger context window

# 3. Set in backend/.env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2
```

Then restart the backend. The Q&A interface will show a green "Local · llama3.2" badge.

---

## Failure modes

| Scenario | Provider | Behavior |
|----------|----------|---------|
| No documents indexed in room | both | Returns hardcoded message; no LLM call made |
| ChromaDB returns no results | both | Returns "couldn't find relevant information"; no LLM call made |
| `ANTHROPIC_API_KEY` not set | anthropic | Raises `ValueError` with clear message; HTTP 500 |
| Anthropic rate limit / API error | anthropic | Exception propagates; HTTP 500 with detail |
| Ollama server not running | ollama | `httpx.ConnectError`; HTTP 500 — start Ollama first |
| Model not pulled in Ollama | ollama | Ollama returns 404; HTTP 500 — run `ollama pull {model}` |
| LLM returns empty content | both | Falls back to `"Unable to generate answer."` |

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
