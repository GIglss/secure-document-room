import os
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_current_user
from services.audit_service import log_event

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
router = APIRouter(prefix="/rooms", tags=["invites"])


@router.post("/{room_id}/invites", response_model=schemas.InviteResult, status_code=201)
def create_invite(
    room_id: str,
    payload: schemas.InviteCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.status != "active":
        raise HTTPException(status_code=400, detail="Room is not active")

    # Check if already invited
    existing = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.email == payload.email,
        models.RoomMember.status != "revoked",
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="This email has already been invited")

    token = str(uuid.uuid4())
    member = models.RoomMember(
        room_id=room_id,
        email=payload.email,
        name=payload.name,
        invite_token=token,
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    log_event(db, room_id, "member_invited", {"email": payload.email}, sender_id=current_user.id)
    invite_link = f"{FRONTEND_URL}/join/{token}"
    return {"invite_token": token, "invite_link": invite_link, "member": member}


@router.get("/{room_id}/members", response_model=list[schemas.MemberOut])
def list_members(
    room_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return db.query(models.RoomMember).filter(models.RoomMember.room_id == room_id).all()


@router.delete("/{room_id}/members/{member_id}", status_code=204)
def revoke_member(
    room_id: str,
    member_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == current_user.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    member = db.query(models.RoomMember).filter(models.RoomMember.id == member_id, models.RoomMember.room_id == room_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.status = "revoked"
    db.commit()
    log_event(db, room_id, "member_revoked", {"email": member.email}, sender_id=current_user.id, member_id=member_id)
