"""Recipient session lifecycle endpoint.

POST /api/session/close marks the recipient's sandbox session as closed so an
external cleanup listener can destroy the ephemeral sandbox.

The body is parsed manually (instead of a Pydantic model) because the frontend
also calls this via navigator.sendBeacon on pagehide, which must use a simple
content type (text/plain) to avoid a CORS preflight the closing page can't
complete. The token is accepted either as a Bearer header or in the JSON body.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
import models
from services.audit_service import log_event
from services.session_service import close_session

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/close")
async def close_recipient_session(request: Request, db: Session = Depends(get_db)):
    token = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8")) if raw else {}
            token = (data.get("session_token") or "").strip() or None
        except Exception:
            token = None
    if not token:
        raise HTTPException(status_code=401, detail="session_token required")

    member = db.query(models.RoomMember).filter(
        models.RoomMember.session_token == token,
    ).first()
    if not member or member.status != "accepted":
        raise HTTPException(status_code=403, detail="Invalid session")
    if member.session_expires_at and member.session_expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session expired")

    close_session(db, member)
    log_event(db, member.room_id, "session_closed", {"email": member.email}, member_id=member.id)
    return {"status": "closed", "room_id": member.room_id}
