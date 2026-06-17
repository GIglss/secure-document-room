import json
from datetime import datetime
from sqlalchemy.orm import Session
import models


def log_event(
    db: Session,
    room_id: str,
    event_type: str,
    event_data: dict = None,
    sender_id: int = None,
    member_id: str = None,
    ip_address: str = None,
) -> models.AuditLog:
    entry = models.AuditLog(
        room_id=room_id,
        sender_id=sender_id,
        member_id=member_id,
        event_type=event_type,
        event_data=json.dumps(event_data or {}),
        ip_address=ip_address,
        created_at=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
