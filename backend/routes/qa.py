import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_optional_user
from services.rag_engine import answer_question
from services.audit_service import log_event

router = APIRouter(prefix="/rooms", tags=["qa"])


def _resolve_access(room_id: str, payload: schemas.QARequest, current_user, db: Session):
    """Returns (sender_id, member_id) for whoever is accessing."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
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
        if member and member.status == "accepted":
            return room, None, member.id
        raise HTTPException(status_code=403, detail="Invalid session or terms not accepted")

    raise HTTPException(status_code=401, detail="Authentication required")


@router.post("/{room_id}/qa", response_model=schemas.QAResponse)
def ask_question(
    room_id: str,
    payload: schemas.QARequest,
    request: Request,
    current_user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    room, sender_id, member_id = _resolve_access(room_id, payload, current_user, db)

    result = answer_question(room_id, payload.question)
    question_id = str(uuid.uuid4())

    log_event(
        db,
        room_id,
        "question_asked",
        {
            "question": payload.question,
            "answer_preview": result["answer"][:200],
            "citation_count": len(result["citations"]),
        },
        sender_id=sender_id,
        member_id=member_id,
        ip_address=request.client.host if request.client else None,
    )

    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "question_id": question_id,
    }
