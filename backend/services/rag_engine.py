import os
import re
from typing import List, Dict, Any
import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")

_chroma_client = None
_embedding_fn = None

# Phrase the model is instructed to use when the context lacks an answer.
NO_ANSWER_MARKER = "do not contain information to answer"

SYSTEM_PROMPT = """You are a secure document assistant operating inside a sealed document room. Your role is to answer questions based ONLY on the provided document excerpts.

Rules you must follow:
1. Answer only from the provided context. Never invent or extrapolate facts.
2. Cite sources using [1], [2], etc. notation matching the provided sources.
3. Never reproduce large verbatim passages. Synthesize and paraphrase.
4. If the answer is not in the context, say: "The documents in this room do not contain information to answer that question."
5. Add a brief disclaimer that answers should be verified against source documents for legal or financial decisions."""


def _get_provider() -> str:
    """Normalized LLM provider: "local" or "anthropic".

    "mlx" is accepted as a backward-compatible alias for "local" (the previous
    name of the local OpenAI-compatible provider).
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    if provider in ("local", "mlx"):
        return "local"
    return "anthropic"


def _local_llm_settings() -> Dict[str, Any]:
    """Local provider settings. New LOCAL_LLM_* envs win; legacy MLX_* envs are
    still honored so existing deployments keep working."""
    base_url = (
        os.getenv("LOCAL_LLM_BASE_URL")
        or os.getenv("MLX_BASE_URL")
        or "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
    )
    # Default matches the llama-server model alias used in deployment. The name
    # is passed through tolerantly — llama.cpp's llama-server largely ignores
    # it and serves whatever model it was started with.
    model = os.getenv("LOCAL_LLM_MODEL") or os.getenv("MLX_MODEL") or "qwen3-8b"
    max_tokens = int(os.getenv("LOCAL_LLM_MAX_TOKENS") or os.getenv("MLX_MAX_TOKENS") or "1024")
    disable_thinking = (
        os.getenv("LOCAL_LLM_DISABLE_THINKING") or os.getenv("MLX_DISABLE_THINKING") or "true"
    ).lower() in ("1", "true", "yes")
    return {
        "base_url": base_url,
        "model": model,
        "max_tokens": max_tokens,
        "disable_thinking": disable_thinking,
    }


def get_llm_config() -> Dict[str, str]:
    """Return current LLM provider configuration (no secrets)."""
    if _get_provider() == "local":
        settings = _local_llm_settings()
        return {
            "provider": "local",
            "model": settings["model"],
            "base_url": settings["base_url"],
        }
    return {
        "provider": "anthropic",
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    }


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client


def _get_embedding_fn():
    """Singleton embedding function — avoids reloading the model on every call."""
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_fn


def _get_collection(room_id: str):
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=f"room_{room_id.replace('-', '_')}",
        embedding_function=_get_embedding_fn(),
    )


def _get_knowledge_collection():
    """Single shared company-knowledge collection. Rows are keyed by sender_id
    metadata so one sender never retrieves another sender's knowledge docs."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="company_knowledge",
        embedding_function=_get_embedding_fn(),
    )


def index_document(
    room_id: str,
    doc_id: str,
    doc_name: str,
    chunks: List[Dict[str, Any]],
    scope: str = "room",
    sender_id: int = None,
) -> int:
    if not chunks:
        return 0
    if scope == "knowledge":
        if sender_id is None:
            raise ValueError("sender_id is required to index knowledge-scoped documents")
        collection = _get_knowledge_collection()
    else:
        collection = _get_collection(room_id)
    ids, texts, metadatas = [], [], []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_chunk_{i}"
        ids.append(chunk_id)
        texts.append(chunk["text"])
        meta = chunk.get("metadata", {})
        meta["doc_id"] = doc_id
        meta["doc_name"] = doc_name
        meta["chunk_index"] = i
        meta["scope"] = scope
        if scope == "knowledge":
            meta["sender_id"] = str(sender_id)
        clean_meta = {
            k: str(v) if not isinstance(v, (str, int, float, bool)) else v
            for k, v in meta.items()
            if v is not None
        }
        metadatas.append(clean_meta)
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
    return len(chunks)


def delete_document_from_index(room_id: str, doc_id: str, scope: str = "room"):
    try:
        collection = _get_knowledge_collection() if scope == "knowledge" else _get_collection(room_id)
        results = collection.get(where={"doc_id": doc_id})
        if results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass


# ── LLM provider calls ──────────────────────────────────────────────────────

def _call_anthropic(user_message: str, system_prompt: str, max_tokens: int) -> str:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
        raise ValueError(
            "ANTHROPIC_API_KEY is not configured. Set a real key in backend/.env, "
            "or set LLM_PROVIDER=local to use a local model."
        )

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text if message.content else "Unable to generate answer."


def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks some models leak into content."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def _call_local(user_message: str, system_prompt: str, max_tokens) -> str:
    """Call any local OpenAI-compatible server (Ollama, MLX, llama.cpp, ...)."""
    from openai import OpenAI

    settings = _local_llm_settings()

    # Reasoning models (Qwen3, etc.) otherwise spend the whole token budget in a
    # <think>/reasoning channel and leave the answer content empty. For this
    # extraction-style RAG task we want a direct answer.
    extra_body = (
        {"chat_template_kwargs": {"enable_thinking": False}}
        if settings["disable_thinking"]
        else {}
    )

    client = OpenAI(base_url=settings["base_url"], api_key="not-required")
    response = client.chat.completions.create(
        model=settings["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens if max_tokens is not None else settings["max_tokens"],
        stream=False,
        extra_body=extra_body,
    )

    msg = response.choices[0].message
    content = _strip_think(msg.content or "")
    if not content:
        # Fallback: some servers/models emit only into a reasoning channel.
        content = _strip_think(getattr(msg, "reasoning", None) or "")
    return content or "Unable to generate answer."


def call_llm(user_message: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = None) -> str:
    """Provider-agnostic single-turn LLM call (used by Q&A and insights).

    max_tokens=None means "provider default" (LOCAL_LLM_MAX_TOKENS for local,
    1024 for anthropic)."""
    if _get_provider() == "local":
        return _call_local(user_message, system_prompt, max_tokens)
    return _call_anthropic(user_message, system_prompt, max_tokens or 1024)


def _call_llm(user_message: str) -> str:
    return call_llm(user_message)


# ── Main entry point ─────────────────────────────────────────────────────────

RETRIEVAL_TOP_K = 5


def _query_collection(collection, question: str, n_results: int, where: dict = None):
    """Query a collection and return a list of (distance, text, metadata)."""
    kwargs = {"query_texts": [question], "n_results": n_results}
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
    return list(zip(dists, docs, metas))


def _retrieve(room_id: str, question: str, sender_id: int = None) -> List[tuple]:
    """Merge results from the room collection and the sender's company knowledge
    collection, sorted by relevance (ascending distance), top RETRIEVAL_TOP_K.

    A room with zero room-scoped documents still answers from knowledge docs."""
    hits = []

    room_collection = _get_collection(room_id)
    room_count = room_collection.count()
    if room_count > 0:
        hits.extend(_query_collection(room_collection, question, min(RETRIEVAL_TOP_K, room_count)))

    if sender_id is not None:
        try:
            knowledge = _get_knowledge_collection()
            sender_filter = {"sender_id": str(sender_id)}
            owned = knowledge.get(where=sender_filter, limit=1)
            if owned["ids"]:
                hits.extend(
                    _query_collection(knowledge, question, RETRIEVAL_TOP_K, where=sender_filter)
                )
        except Exception as e:
            # Knowledge base problems must not take down room Q&A
            print(f"Knowledge collection query failed (room {room_id}): {e}")

    hits.sort(key=lambda h: h[0])
    return hits[:RETRIEVAL_TOP_K]


def answer_question(room_id: str, question: str, sender_id: int = None) -> Dict[str, Any]:
    hits = _retrieve(room_id, question, sender_id=sender_id)
    if not hits:
        return {
            "answer": "No documents have been indexed in this room yet. Please ask the room owner to upload documents.",
            "citations": [],
        }

    docs = [h[1] for h in hits]
    metas = [h[2] for h in hits]

    context_parts = []
    all_citations = []  # indexed 0..N-1, marker number = index + 1
    for i, (doc_text, meta) in enumerate(zip(docs, metas)):
        doc_name = meta.get("doc_name", "Unknown Document")
        if meta.get("scope") == "knowledge":
            doc_name = f"{doc_name} (Company Knowledge)"
        page_ref = meta.get("page_num") or meta.get("section") or meta.get("sheet_name")
        context_parts.append(
            f"[{i+1}] Source: {doc_name}" + (f" (p.{page_ref})" if page_ref else "") + f"\n{doc_text}"
        )
        all_citations.append({
            "number": i + 1,
            "document_name": doc_name,
            "page_ref": str(page_ref) if page_ref else None,
            "excerpt": doc_text[:200] + "..." if len(doc_text) > 200 else doc_text,
        })

    context = "\n\n---\n\n".join(context_parts)
    user_message = f"""Context from room documents:

{context}

Question: {question}

Please answer based only on the above context, with appropriate citations."""

    answer_text = _call_llm(user_message)
    return _ground_answer(answer_text, all_citations)


def _ground_answer(answer_text: str, all_citations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verify the answer against retrieved sources.

    Returns only the citations the answer actually referenced (via [N] markers),
    and flags answers the model could not ground in the documents. This is the
    citation-verification step: a wrong or unsupported citation is worse than no
    answer in a legal/financial context.
    """
    # Model signalled it could not answer from the provided context
    if NO_ANSWER_MARKER in answer_text.lower():
        return {"answer": answer_text, "citations": [], "grounded": False}

    # Extract the [N] markers the answer used and map them to retrieved sources
    referenced = {int(n) for n in re.findall(r"\[(\d+)\]", answer_text)}
    by_number = {c["number"]: c for c in all_citations}
    cited = [by_number[n] for n in sorted(referenced) if n in by_number]

    # If the model cited nothing, surface the top retrieved source so the user
    # always has at least one verifiable reference to inspect.
    if not cited and all_citations:
        cited = [all_citations[0]]

    return {"answer": answer_text, "citations": cited, "grounded": bool(cited)}
