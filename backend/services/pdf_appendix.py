"""Conversation-summary appendix for document downloads.

When the recipient (or sender) downloads a room document with
?with_appendix=1, we append "Conversation Summary" pages to the original PDF:

  1. An LLM-generated summary of the recipient's Q&A history in the room.
  2. The verbatim list of questions asked, each with a short answer excerpt.

If the LLM is unreachable, we fall back to the verbatim Q&A list without the
generated summary — the download must NEVER fail because of the LLM.
"""
import html
import json
from io import BytesIO
from typing import List, Optional

from sqlalchemy.orm import Session

import models
from services.rag_engine import call_llm

SUMMARY_SYSTEM_PROMPT = """You summarize a due-diligence Q&A conversation held inside a secure document room. You receive the list of questions the recipient asked and short excerpts of the answers. Write a concise summary (one or two paragraphs, plain prose, no markdown) of what the recipient focused on and what was covered. Do not invent facts beyond the provided exchanges."""


def collect_qa_history(db: Session, room_id: str) -> List[dict]:
    """The recipient's Q&A history in the room, oldest first.

    Sourced from the immutable audit log ("question_asked" events with a
    member_id — i.e. asked by the room's recipient, not the sender)."""
    events = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.room_id == room_id,
            models.AuditLog.event_type == "question_asked",
            models.AuditLog.member_id.isnot(None),
        )
        .order_by(models.AuditLog.created_at.asc())
        .all()
    )
    items = []
    for e in events:
        try:
            data = json.loads(e.event_data or "{}")
        except Exception:
            data = {}
        question = (data.get("question") or "").strip()
        if not question:
            continue
        items.append({
            "question": question,
            "answer_excerpt": (data.get("answer_preview") or "").strip(),
            "asked_at": e.created_at,
        })
    return items


def generate_conversation_summary(qa_items: List[dict]) -> Optional[str]:
    """LLM summary of the Q&A history. Returns None if the LLM is unreachable
    or fails in any way (callers fall back to the verbatim list)."""
    if not qa_items:
        return None
    lines = []
    for i, item in enumerate(qa_items, 1):
        lines.append(f"Q{i}: {item['question']}")
        if item.get("answer_excerpt"):
            lines.append(f"A{i} (excerpt): {item['answer_excerpt']}")
    try:
        summary = call_llm(
            "Conversation to summarize:\n\n" + "\n".join(lines),
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            max_tokens=600,
        )
        summary = (summary or "").strip()
        return summary or None
    except Exception as e:
        print(f"Conversation summary generation failed (LLM unreachable?): {e}")
        return None


def _esc(text: str) -> str:
    """Escape for reportlab Paragraph markup."""
    return html.escape(text or "", quote=False)


def build_appendix_pdf(room_name: str, qa_items: List[dict], summary: Optional[str]) -> bytes:
    """Render the appendix pages with reportlab and return the PDF bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("AppendixTitle", parent=styles["Title"], spaceAfter=6)
    meta_style = ParagraphStyle("AppendixMeta", parent=styles["Normal"], textColor="#666666", fontSize=9, spaceAfter=14)
    heading_style = ParagraphStyle("AppendixHeading", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle("AppendixBody", parent=styles["Normal"], leading=14, spaceAfter=8)
    question_style = ParagraphStyle("AppendixQuestion", parent=styles["Normal"], leading=14, spaceBefore=8, spaceAfter=2)
    answer_style = ParagraphStyle(
        "AppendixAnswer", parent=styles["Normal"], leading=13, fontSize=9,
        textColor="#444444", leftIndent=0.6 * cm, spaceAfter=6,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title="Conversation Summary",
    )

    story = [Paragraph("Conversation Summary", title_style)]
    story.append(Paragraph(f"Room: {_esc(room_name)}", meta_style))

    if summary:
        story.append(Paragraph("Summary", heading_style))
        for para in summary.split("\n"):
            if para.strip():
                story.append(Paragraph(_esc(para.strip()), body_style))
    else:
        story.append(Paragraph(
            "An AI-generated summary is unavailable for this download. "
            "The full list of questions asked is included below.",
            body_style,
        ))

    story.append(Paragraph("Questions Asked", heading_style))
    if not qa_items:
        story.append(Paragraph("No questions were asked in this room.", body_style))
    else:
        for i, item in enumerate(qa_items, 1):
            asked_at = item.get("asked_at")
            when = f" <font size=8 color='#888888'>({asked_at.strftime('%Y-%m-%d %H:%M')} UTC)</font>" if asked_at else ""
            story.append(Paragraph(f"<b>{i}. {_esc(item['question'])}</b>{when}", question_style))
            if item.get("answer_excerpt"):
                story.append(Paragraph(_esc(item["answer_excerpt"]), answer_style))

    story.append(Spacer(1, 12))
    doc.build(story)
    return buf.getvalue()


def append_appendix(original_pdf_path: str, appendix_bytes: bytes) -> bytes:
    """Merge the original PDF with the appendix pages (pypdf) and return the
    combined PDF bytes."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(original_pdf_path))
    writer.append(PdfReader(BytesIO(appendix_bytes)))
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def build_pdf_with_conversation_appendix(db: Session, room: models.Room, original_pdf_path: str) -> bytes:
    """Full pipeline: history -> (best-effort) LLM summary -> appendix -> merge."""
    qa_items = collect_qa_history(db, room.id)
    summary = generate_conversation_summary(qa_items)
    appendix = build_appendix_pdf(room.name, qa_items, summary)
    return append_appendix(original_pdf_path, appendix)
