import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
import config
from auth import get_optional_user
from services.rag_engine import answer_question
from services.audit_service import log_event
from services.rate_limit import check_rate_limit

router = APIRouter(prefix="/rooms", tags=["qa"])


def _resolve_access(room_id: str, payload: schemas.QARequest, current_user, db: Session):
    """Returns (room, sender_id, member_id) for whoever is accessing."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Enforce expiry on the Q&A path itself (don't rely on a sender reload)
    if room.status == "active" and room.expires_at and room.expires_at < datetime.utcnow():
        room.status = "expired"
        db.commit()
        log_event(db, room_id, "room_expired", {})

    if room.status != "active":
        raise HTTPException(status_code=403, detail="Room is not active")

    # Sender access
    if current_user and room.sender_id == current_user.id:
        return room, current_user.id, None

    # Recipient access via session_token
    if payload.session_token:
        member = db.query(models.RoomMember).filter(
            models.RoomMember.session_token == payload.session_token,
            models.RoomMember.room_id == room_id,
        ).first()
        if not member or member.status != "accepted":
            raise HTTPException(status_code=403, detail="Invalid session or terms not accepted")
        if member.session_expires_at and member.session_expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="Session expired. Please rejoin the room.")
        return room, None, member.id

    raise HTTPException(status_code=401, detail="Authentication required")


@router.post("/{room_id}/qa", response_model=schemas.QAResponse)
def ask_question(
    room_id: str,
    payload: schemas.QARequest,
    request: Request,
    current_user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    room, sender_id, member_id = _resolve_access(room_id, payload, current_user, db)

    # Rate limit per accessor, per room — deters bulk content extraction
    rate_key = f"{room_id}:{member_id or f'sender_{sender_id}'}"
    if not check_rate_limit(rate_key, config.QA_RATE_MAX, config.QA_RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait before asking another question.",
        )

    try:
        result = answer_question(room_id, payload.question)
    except ValueError as e:
        # Misconfiguration (e.g. missing/placeholder API key) — actionable message
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Provider/network failure — return a handled error so it carries CORS
        # headers and the client sees the reason instead of "Failed to fetch"
        raise HTTPException(status_code=502, detail=f"AI provider error: {e}")
    question_id = str(uuid.uuid4())

    log_event(
        db,
        room_id,
        "question_asked",
        {
            "question": payload.question,
            "answer_preview": result["answer"][:200],
            "citation_count": len(result["citations"]),
            "grounded": result.get("grounded", True),
        },
        sender_id=sender_id,
        member_id=member_id,
        ip_address=request.client.host if request.client else None,
    )

    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "grounded": result.get("grounded", True),
        "question_id": question_id,
    }
