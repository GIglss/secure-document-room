from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_current_user
from services.audit_service import log_event

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _check_expiry(room: models.Room, db: Session):
    if room.status == "active" and room.expires_at and room.expires_at < datetime.utcnow():
        room.status = "expired"
        db.commit()


@router.get("", response_model=list[schemas.RoomOut])
def list_rooms(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    rooms = db.query(models.Room).filter(models.Room.sender_id == current_user.id).order_by(models.Room.created_at.desc()).all()
    result = []
    for room in rooms:
        _check_expiry(room, db)
        r = schemas.RoomOut.model_validate(room)
        r.document_count = len(room.documents)
        r.member_count = len([m for m in room.members if m.status != "revoked"])
        result.append(r)
    return result


@router.post("", response_model=schemas.RoomOut, status_code=201)
def create_room(
    payload: schemas.RoomCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = models.Room(
        sender_id=current_user.id,
        name=payload.name,
        description=payload.description,
        expires_at=payload.expires_at,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    log_event(db, room.id, "room_created", {"name": room.name}, sender_id=current_user.id)
    r = schemas.RoomOut.model_validate(room)
    r.document_count = 0
    r.member_count = 0
    return r


@router.get("/{room_id}", response_model=schemas.RoomOut)
def get_room(
    room_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    _check_expiry(room, db)
    r = schemas.RoomOut.model_validate(room)
    r.document_count = len(room.documents)
    r.member_count = len([m for m in room.members if m.status != "revoked"])
    return r


@router.patch("/{room_id}", response_model=schemas.RoomOut)
def update_room(
    room_id: str,
    payload: schemas.RoomUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if payload.status:
        room.status = payload.status
    if payload.expires_at is not None:
        room.expires_at = payload.expires_at
    if payload.name:
        room.name = payload.name
    if payload.description is not None:
        room.description = payload.description
    room.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(room)
    r = schemas.RoomOut.model_validate(room)
    r.document_count = len(room.documents)
    r.member_count = len([m for m in room.members if m.status != "revoked"])
    return r


@router.delete("/{room_id}", status_code=204)
def delete_room(
    room_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    room.status = "revoked"
    room.updated_at = datetime.utcnow()
    db.commit()
    log_event(db, room_id, "room_revoked", {}, sender_id=current_user.id)
