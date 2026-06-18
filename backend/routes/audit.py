import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_current_user
from services.audit_service import log_event

router = APIRouter(prefix="/rooms", tags=["audit"])


@router.get("/{room_id}/audit", response_model=list[schemas.AuditEventOut])
def get_audit_log(
    room_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    events = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.room_id == room_id)
        .order_by(models.AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return events


@router.get("/{room_id}/audit/export")
def export_audit_log(
    room_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    events = db.query(models.AuditLog).filter(models.AuditLog.room_id == room_id).order_by(models.AuditLog.created_at.asc()).all()

    # Build member email lookup
    members = {m.id: m.email for m in db.query(models.RoomMember).filter(models.RoomMember.room_id == room_id).all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "event_type", "actor_email", "details"])

    for event in events:
        actor = current_user.email if event.sender_id == current_user.id else members.get(event.member_id, "unknown")
        try:
            details = json.loads(event.event_data or "{}")
        except Exception:
            details = {}
        writer.writerow([
            event.created_at.isoformat(),
            event.event_type,
            actor,
            json.dumps(details),
        ])

    log_event(db, room_id, "audit_exported", {}, sender_id=current_user.id)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_{room_id[:8]}.csv"},
    )
