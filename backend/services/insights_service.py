"""Conversation insights: classify each successful Q&A exchange into an
anonymized analytics row (the backbone of the company dashboard).

Runs as a FastAPI background task after the answer has already been returned —
a classification failure must NEVER break or delay Q&A, so everything here is
log-and-continue.
"""
import json
import os
import re
from datetime import datetime

from database import SessionLocal
import models
from services.rag_engine import call_llm

CATEGORIES = [
    "pricing",
    "legal_terms",
    "technical_capabilities",
    "security_compliance",
    "integration",
    "support",
    "timeline_delivery",
    "competitive_comparison",
    "documentation_content",
    "other",
]

CLASSIFY_SYSTEM_PROMPT = """You are an analytics classifier. You receive a question asked inside a secure document room. Respond with ONLY a JSON object, no other text:

{"category": "<category>", "topic_label": "<label>"}

Rules:
1. "category" must be EXACTLY one of: pricing, legal_terms, technical_capabilities, security_compliance, integration, support, timeline_delivery, competitive_comparison, documentation_content, other.
2. "topic_label" is a 3-8 word anonymized topic summary. It must NOT contain any personal names, company names, product names, email addresses, or any other personally identifiable information. Describe the topic generically (e.g. "annual subscription pricing tiers", "data retention policy details").
3. Output only the JSON object."""


def _parse_classification(raw: str) -> tuple[str, str]:
    """Best-effort parse of the LLM output. Returns (category, topic_label)."""
    category, topic_label = "other", "general question"
    if not raw:
        return category, topic_label

    # Try strict JSON first (possibly wrapped in prose or code fences)
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            cand = str(data.get("category", "")).strip().lower()
            if cand in CATEGORIES:
                category = cand
            label = str(data.get("topic_label", "")).strip()
            if label:
                topic_label = label[:120]
            return category, topic_label
        except Exception:
            pass

    # Fallback: scan for a known category token anywhere in the output
    lowered = raw.lower()
    for cand in CATEGORIES:
        if cand in lowered:
            category = cand
            break
    return category, topic_label


def _mirror_to_azure_table(insight: models.QAInsight):
    """Optionally mirror the insight row to an Azure Table named "insights".

    Config absent = local-only, silently skipped. Any Azure failure is logged
    and swallowed — the SQLite row is the source of truth.
    """
    endpoint = os.getenv("AZURE_TABLES_ENDPOINT", "").strip()
    conn_str = os.getenv("AZURE_TABLES_CONNECTION_STRING", "").strip()
    if not endpoint and not conn_str:
        return
    try:
        from azure.data.tables import TableServiceClient

        if conn_str:
            service = TableServiceClient.from_connection_string(conn_str)
        else:
            from azure.identity import DefaultAzureCredential

            service = TableServiceClient(endpoint=endpoint, credential=DefaultAzureCredential())

        table = service.create_table_if_not_exists("insights")
        entity = {
            "PartitionKey": insight.room_id,
            "RowKey": insight.id,
            "member_id": insight.member_id or "",
            "category": insight.category,
            "topic_label": insight.topic_label,
            "sharing_mode": insight.sharing_mode,
            "question_text": insight.question_text or "",
            "answer_text": insight.answer_text or "",
            "created_at": insight.created_at.isoformat(),
        }
        table.upsert_entity(entity)
    except Exception as e:
        print(f"Azure Tables mirror failed for insight {insight.id}: {e}")


def generate_insight(room_id: str, member_id: str, question: str, answer: str):
    """Background task: classify one Q&A exchange and persist the insight.

    member_id is None when the sender queried their own room; the sender owns
    that data, so it is stored with sharing_mode "full".
    """
    db = SessionLocal()
    try:
        sharing_mode = "full"  # sender's own questions
        if member_id:
            member = db.query(models.RoomMember).filter(models.RoomMember.id == member_id).first()
            sharing_mode = (member.sharing_mode if member else None) or "anonymized"

        try:
            raw = call_llm(
                f"Question: {question}",
                system_prompt=CLASSIFY_SYSTEM_PROMPT,
                max_tokens=200,
            )
            category, topic_label = _parse_classification(raw)
        except Exception as e:
            # Classification failure must never break Q&A analytics entirely —
            # log and skip this exchange.
            print(f"Insight classification failed for room {room_id}: {e}")
            return

        insight = models.QAInsight(
            room_id=room_id,
            member_id=member_id,
            category=category,
            topic_label=topic_label,
            sharing_mode=sharing_mode,
            question_text=question if sharing_mode == "full" else None,
            answer_text=answer if sharing_mode == "full" else None,
            created_at=datetime.utcnow(),
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)

        _mirror_to_azure_table(insight)
    except Exception as e:
        db.rollback()
        print(f"Insight persistence failed for room {room_id}: {e}")
    finally:
        db.close()
