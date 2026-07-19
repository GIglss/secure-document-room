import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
import config
from services.audit_service import log_event
from services.email_service import acs_email_configured, send_verification_email
from services.session_service import record_login

router = APIRouter(prefix="/join", tags=["join"])

TERMS_TEXT = """SECURE DOCUMENT ROOM — TERMS OF USE

By entering this room, you agree that:

1. The documents shared in this room are provided solely for your legitimate due diligence purpose. You may view and download them, but you will not share them with unauthorized parties.

2. You will use AI-generated answers solely for authorized analysis and will not share answers with unauthorized parties. Your questions are processed by a local AI model inside an isolated sandbox that is destroyed after your engagement — they are never sent to a public AI provider.

3. All interactions within this room are logged and may be reviewed by the room owner.

4. Any breach of these terms may result in legal liability, including but not limited to claims for breach of confidentiality, NDA violations, or privilege waiver.

5. The AI answers provided are synthesized summaries and do not constitute legal, financial, or investment advice. You agree to verify material facts against source documents.

6. Your identity and all questions asked are recorded in an immutable audit trail.

This agreement creates a legally binding obligation. If you do not agree, do not enter the room."""


@router.get("/{token}", response_model=schemas.JoinInfo)
def get_join_info(token: str, db: Session = Depends(get_db)):
    member = db.query(models.RoomMember).filter(models.RoomMember.invite_token == token).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid or expired invite link")
    if member.status == "revoked":
        raise HTTPException(status_code=403, detail="Your access to this room has been revoked")
    room = db.query(models.Room).filter(models.Room.id == member.room_id).first()
    if not room or room.status != "active":
        raise HTTPException(status_code=403, detail="This room is no longer active")
    sender = db.query(models.User).filter(models.User.id == room.sender_id).first()
    return {
        "room_name": room.name,
        "description": room.description,
        "sender_name": sender.name if sender else "Unknown",
        "status": member.status,
        "terms_text": TERMS_TEXT,
    }


@router.post("/{token}/verify")
def verify_email(token: str, payload: schemas.VerifyEmailRequest, db: Session = Depends(get_db)):
    member = db.query(models.RoomMember).filter(models.RoomMember.invite_token == token).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    if member.status == "revoked":
        raise HTTPException(status_code=403, detail="Access revoked")
    if member.email.lower() != payload.email.lower():
        raise HTTPException(status_code=400, detail="Email does not match the invite")
    # Cryptographically-random 6-digit code with expiry + attempt reset
    code = f"{secrets.randbelow(1000000):06d}"
    member.verification_code = code
    member.code_expires_at = datetime.utcnow() + timedelta(minutes=config.CODE_TTL_MINUTES)
    member.verification_attempts = 0
    db.commit()

    # Real email path: if Azure Communication Services is configured, send the
    # code by email and NEVER include it in the API response.
    if acs_email_configured():
        room = db.query(models.Room).filter(models.Room.id == member.room_id).first()
        try:
            send_verification_email(payload.email, code, room.name if room else "Secure Document Room")
        except Exception as e:
            print(f"ACS email send failed for {payload.email}: {e}")
            raise HTTPException(status_code=502, detail="Failed to send verification email. Please try again.")
        return {"message": "Verification code sent to your email"}

    # Dev mock path (no email infrastructure configured)
    print(f"[DEV] Verification code for {payload.email}: {code}")
    response = {"message": "Verification code sent"}
    # Demo convenience ONLY in dev: surface the code so the flow can be tested
    # without email infrastructure. Never enabled in production (DEV_MODE=false).
    if config.DEV_MODE:
        response["demo_code"] = code
    return response


@router.post("/{token}/confirm", response_model=schemas.SessionResponse)
def confirm_code(token: str, payload: schemas.ConfirmCodeRequest, db: Session = Depends(get_db)):
    member = db.query(models.RoomMember).filter(models.RoomMember.invite_token == token).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    if member.email.lower() != payload.email.lower():
        raise HTTPException(status_code=400, detail="Email mismatch")
    if not member.verification_code:
        raise HTTPException(status_code=400, detail="No active code. Request a new verification code.")
    if member.code_expires_at and member.code_expires_at < datetime.utcnow():
        member.verification_code = None
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code expired. Request a new one.")
    if member.verification_attempts >= config.CODE_MAX_ATTEMPTS:
        member.verification_code = None
        db.commit()
        raise HTTPException(status_code=429, detail="Too many failed attempts. Request a new verification code.")
    if not secrets.compare_digest(member.verification_code, payload.code):
        member.verification_attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid verification code")
    # Success — issue session and clear the one-time code
    session_token = secrets.token_urlsafe(32)
    member.status = "verified"
    member.session_token = session_token
    member.session_expires_at = datetime.utcnow() + timedelta(hours=config.SESSION_TTL_HOURS)
    member.verified_at = datetime.utcnow()
    member.verification_code = None
    member.code_expires_at = None
    db.commit()
    room = db.query(models.Room).filter(models.Room.id == member.room_id).first()
    log_event(db, member.room_id, "member_verified", {"email": member.email}, member_id=member.id)
    return {
        "session_token": session_token,
        "room_id": member.room_id,
        "room_name": room.name if room else None,
        "sharing_mode": member.sharing_mode or "anonymized",
    }


@router.post("/{token}/accept", response_model=schemas.SessionResponse)
def accept_terms(token: str, payload: schemas.AcceptTermsRequest, request: Request, db: Session = Depends(get_db)):
    member = db.query(models.RoomMember).filter(
        models.RoomMember.invite_token == token,
        models.RoomMember.session_token == payload.session_token,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Invalid session")
    if member.status not in ("verified",):
        raise HTTPException(status_code=400, detail="Must verify email first")
    member.status = "accepted"
    member.accepted_at = datetime.utcnow()
    if payload.sharing_mode is not None:
        member.sharing_mode = payload.sharing_mode
    db.commit()
    # Session lifecycle signal for the sandbox cleanup listener
    record_login(db, member)
    room = db.query(models.Room).filter(models.Room.id == member.room_id).first()
    log_event(
        db, member.room_id, "member_accepted",
        {"email": member.email, "sharing_mode": member.sharing_mode or "anonymized"},
        member_id=member.id,
        ip_address=request.client.host if request.client else None,
    )
    return {
        "session_token": payload.session_token,
        "room_id": member.room_id,
        "room_name": room.name if room else None,
        "sharing_mode": member.sharing_mode or "anonymized",
    }
