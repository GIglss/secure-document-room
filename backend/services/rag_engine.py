import os
from typing import List, Dict, Any
import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")

_chroma_client = None

SYSTEM_PROMPT = """You are a secure document assistant operating inside a sealed document room. Your role is to answer questions based ONLY on the provided document excerpts.

Rules you must follow:
1. Answer only from the provided context. Never invent or extrapolate facts.
2. Cite sources using [1], [2], etc. notation matching the provided sources.
3. Never reproduce large verbatim passages. Synthesize and paraphrase.
4. If the answer is not in the context, say: "The documents in this room do not contain information to answer that question."
5. Add a brief disclaimer that answers should be verified against source documents for legal or financial decisions."""


def get_llm_config() -> Dict[str, str]:
    """Return current LLM provider configuration (no secrets)."""
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "ollama":
        return {
            "provider": "ollama",
            "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
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


def _get_collection(room_id: str):
    client = get_chroma_client()
    ef = embedding_functions.DefaultEmbeddingFunction()
    return client.get_or_create_collection(
        name=f"room_{room_id.replace('-', '_')}",
        embedding_function=ef,
    )


def index_document(room_id: str, doc_id: str, doc_name: str, chunks: List[Dict[str, Any]]) -> int:
    if not chunks:
        return 0
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
        clean_meta = {
            k: str(v) if not isinstance(v, (str, int, float, bool)) else v
            for k, v in meta.items()
            if v is not None
        }
        metadatas.append(clean_meta)
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
    return len(chunks)


def delete_document_from_index(room_id: str, doc_id: str):
    try:
        collection = _get_collection(room_id)
        results = collection.get(where={"doc_id": doc_id})
        if results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass


# ── LLM provider calls ──────────────────────────────────────────────────────

def _call_anthropic(user_message: str) -> str:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set in the environment")

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text if message.content else "Unable to generate answer."


def _call_ollama(user_message: str) -> str:
    import httpx

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")

    response = httpx.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", {}).get("content", "Unable to generate answer.")


def _call_llm(user_message: str) -> str:
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "ollama":
        return _call_ollama(user_message)
    return _call_anthropic(user_message)


# ── Main entry point ─────────────────────────────────────────────────────────

def answer_question(room_id: str, question: str) -> Dict[str, Any]:
    collection = _get_collection(room_id)
    count = collection.count()
    if count == 0:
        return {
            "answer": "No documents have been indexed in this room yet. Please ask the room owner to upload documents.",
            "citations": [],
        }

    results = collection.query(query_texts=[question], n_results=min(5, count))
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []

    if not docs:
        return {
            "answer": "I couldn't find relevant information to answer your question.",
            "citations": [],
        }

    context_parts = []
    citations = []
    for i, (doc_text, meta) in enumerate(zip(docs, metas)):
        doc_name = meta.get("doc_name", "Unknown Document")
        page_ref = meta.get("page_num") or meta.get("section") or meta.get("sheet_name")
        context_parts.append(
            f"[{i+1}] Source: {doc_name}" + (f" (p.{page_ref})" if page_ref else "") + f"\n{doc_text}"
        )
        citations.append({
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
    return {"answer": answer_text, "citations": citations}
