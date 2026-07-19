import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
import models, schemas
import config
from auth import get_current_user, bearer_scheme, decode_token
from services.audit_service import log_event
from services.document_processor import process_document
from services.rag_engine import index_document, delete_document_from_index
from services.session_service import touch_activity

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

router = APIRouter(prefix="/rooms", tags=["documents"])


def _sanitize_filename(filename: str) -> str:
    """Strip any path components and unsafe characters to prevent traversal."""
    base = os.path.basename(filename or "").replace("\\", "")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return base or "upload"


def _get_room_or_404(room_id: str, sender_id: int, db: Session) -> models.Room:
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == sender_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def _validate_pdf_upload(filename: str, content: bytes):
    """Enforce v2 upload constraints: PDF only, readable, max page count.

    Raises HTTPException(400) with a clear message on any violation."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != "pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted. Please convert your document to PDF before uploading.",
        )
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            # Try an empty owner/user password; refuse if it stays locked
            try:
                if not reader.decrypt(""):
                    raise ValueError("password-protected")
            except Exception:
                raise ValueError("password-protected")
        page_count = len(reader.pages)
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="This PDF is password-protected. Please remove the password and re-upload.",
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="The file could not be read as a valid PDF.",
        )
    if page_count > config.MAX_PDF_PAGES:
        raise HTTPException(
            status_code=400,
            detail=f"PDF has {page_count} pages — the maximum is {config.MAX_PDF_PAGES} pages.",
        )
    if page_count == 0:
        raise HTTPException(status_code=400, detail="The PDF contains no pages.")


def _resolve_member_session(room_id: str, token: str, db: Session) -> Optional[models.RoomMember]:
    """Resolve a recipient session token to an accepted, unexpired room member.
    Same auth pattern as the Q&A route. Returns None when the token doesn't
    belong to this room's recipient."""
    if not token:
        return None
    member = db.query(models.RoomMember).filter(
        models.RoomMember.session_token == token,
        models.RoomMember.room_id == room_id,
    ).first()
    if not member or member.status != "accepted":
        return None
    if member.session_expires_at and member.session_expires_at < datetime.utcnow():
        return None
    return member


def _resolve_room_access(
    room_id: str,
    db: Session,
    credentials: Optional[HTTPAuthorizationCredentials],
    session_token: Optional[str] = None,
) -> Tuple[models.Room, Optional[models.User], Optional[models.RoomMember]]:
    """Authorize either the sender (JWT) or the room's recipient (session token,
    passed as the bearer credential or ?session_token=). Returns
    (room, user_or_None, member_or_None); raises 401/403/404 otherwise."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    bearer = credentials.credentials if credentials else None

    # Sender path: bearer is a valid JWT for the room owner
    if bearer:
        payload = decode_token(bearer)
        if payload and payload.get("sub"):
            user = db.query(models.User).filter(models.User.id == int(payload["sub"])).first()
            if user and room.sender_id == user.id:
                return room, user, None

    # Recipient path: bearer (or explicit session_token) is a member session
    for token in (bearer, session_token):
        member = _resolve_member_session(room_id, token, db)
        if member:
            if room.status != "active":
                raise HTTPException(status_code=403, detail="Room is not active")
            touch_activity(db, member)
            return room, None, member

    raise HTTPException(status_code=401, detail="Authentication required")


def _index_in_background(
    doc_id: str, room_id: str, doc_name: str, file_path: str, file_type: str,
    scope: str = "room", sender_id: int = None,
):
    # Reuse the shared engine via SessionLocal (no per-upload engine creation)
    db = SessionLocal()
    try:
        chunks = process_document(file_path, file_type)
        if not chunks:
            doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
            if doc:
                doc.indexed = False
                doc.chunks_count = 0
                doc.index_error = (
                    "No extractable text found. If this is a scanned or image-only "
                    "PDF, it must be OCR'd before upload."
                )
                db.commit()
            print(f"Indexing produced 0 chunks for doc {doc_id} ({doc_name})")
            return
        count = index_document(room_id, doc_id, doc_name, chunks, scope=scope, sender_id=sender_id)
        doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
        if doc:
            doc.indexed = True
            doc.chunks_count = count
            doc.index_error = None
            db.commit()
    except Exception as e:
        print(f"Indexing error for doc {doc_id}: {e}")
        try:
            doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
            if doc:
                doc.indexed = False
                doc.index_error = f"{type(e).__name__}: {e}"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


@router.post("/{room_id}/documents", response_model=schemas.DocumentOut, status_code=201)
async def upload_document(
    room_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    scope: str = Form("room"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_room_or_404(room_id, current_user.id, db)
    if scope not in ("room", "knowledge"):
        raise HTTPException(status_code=400, detail="scope must be 'room' or 'knowledge'")

    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # v2 constraints (room and knowledge scope alike): PDF only, max page count
    _validate_pdf_upload(file.filename or "", content)
    file_type = "pdf"

    doc_id = str(uuid.uuid4())
    original_filename = _sanitize_filename(file.filename)
    room_upload_dir = os.path.join(UPLOAD_DIR, room_id)
    os.makedirs(room_upload_dir, exist_ok=True)
    safe_name = f"{doc_id}_{original_filename}"
    file_path = os.path.join(room_upload_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(content)

    doc = models.Document(
        id=doc_id,
        room_id=room_id,
        filename=safe_name,
        original_filename=original_filename,
        file_type=file_type,
        file_size=len(content),
        file_path=file_path,
        scope=scope,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(
        _index_in_background, doc_id, room_id, original_filename, file_path, file_type,
        scope, current_user.id,
    )

    log_event(
        db, room_id, "document_uploaded",
        {"filename": original_filename, "size": len(content), "scope": scope},
        sender_id=current_user.id,
    )
    return doc


@router.get("/{room_id}/documents", response_model=list[schemas.DocumentOut])
def list_documents(
    room_id: str,
    session_token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """List room documents. Sender (JWT) sees everything; the room's recipient
    (session token) sees room-scoped documents only (knowledge-base documents
    are internal to the sender's company)."""
    _room, user, member = _resolve_room_access(room_id, db, credentials, session_token)
    query = db.query(models.Document).filter(models.Document.room_id == room_id)
    if member:
        query = query.filter(models.Document.scope == "room")
    return query.all()


@router.get("/{room_id}/documents/{document_id}/file")
def get_document_file(
    room_id: str,
    document_id: str,
    request: Request,
    with_appendix: int = 0,
    session_token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Serve the original PDF, viewable/downloadable by BOTH the sender (JWT)
    and the room's recipient (session token).

    ?with_appendix=1 appends "Conversation Summary" pages: an LLM-generated
    summary of the recipient's Q&A history plus the verbatim question list.
    If the LLM is down, the appendix falls back to the verbatim list — the
    download never fails because of the LLM."""
    room, user, member = _resolve_room_access(room_id, db, credentials, session_token)

    doc_query = db.query(models.Document).filter(
        models.Document.id == document_id, models.Document.room_id == room_id
    )
    if member:
        # Knowledge-base documents are never exposed to recipients
        doc_query = doc_query.filter(models.Document.scope == "room")
    doc = doc_query.first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=410, detail="Document file is no longer available")

    filename = doc.original_filename
    if with_appendix:
        from services.pdf_appendix import build_pdf_with_conversation_appendix

        try:
            pdf_bytes = build_pdf_with_conversation_appendix(db, room, doc.file_path)
            stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
            filename = f"{stem}_with_conversation_summary.pdf"
        except Exception as e:
            # Never fail the download — fall back to the original file
            print(f"Appendix generation failed for doc {doc.id}: {e}")
            with open(doc.file_path, "rb") as f:
                pdf_bytes = f.read()
    else:
        with open(doc.file_path, "rb") as f:
            pdf_bytes = f.read()

    # Audit-log recipient views/downloads (the sender accessing their own
    # upload is not a disclosure event)
    if member:
        log_event(
            db, room_id,
            "document_downloaded" if with_appendix else "document_viewed",
            {
                "filename": doc.original_filename,
                "with_appendix": bool(with_appendix),
                "email": member.email,
            },
            member_id=member.id,
            ip_address=request.client.host if request.client else None,
        )

    safe_filename = _sanitize_filename(filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
    )


@router.delete("/{room_id}/documents/{doc_id}", status_code=204)
def delete_document(
    room_id: str,
    doc_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_room_or_404(room_id, current_user.id, db)
    doc = db.query(models.Document).filter(models.Document.id == doc_id, models.Document.room_id == room_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    delete_document_from_index(room_id, doc_id, scope=doc.scope or "room")
    db.delete(doc)
    db.commit()
    log_event(db, room_id, "document_deleted", {"filename": doc.original_filename}, sender_id=current_user.id)
