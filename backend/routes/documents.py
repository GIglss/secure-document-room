import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_current_user
from services.audit_service import log_event
from services.document_processor import process_document
from services.rag_engine import index_document, delete_document_from_index

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
ALLOWED_TYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

router = APIRouter(prefix="/rooms", tags=["documents"])


def _get_room_or_404(room_id: str, sender_id: int, db: Session) -> models.Room:
    room = db.query(models.Room).filter(models.Room.id == room_id, models.Room.sender_id == sender_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def _detect_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED_TYPES:
        return ext
    return None


def _index_in_background(doc_id: str, room_id: str, doc_name: str, file_path: str, file_type: str, db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    BgSession = sessionmaker(bind=engine)
    db = BgSession()
    try:
        chunks = process_document(file_path, file_type)
        count = index_document(room_id, doc_id, doc_name, chunks)
        doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
        if doc:
            doc.indexed = True
            doc.chunks_count = count
            db.commit()
    except Exception as e:
        print(f"Indexing error for doc {doc_id}: {e}")
    finally:
        db.close()


@router.post("/{room_id}/documents", response_model=schemas.DocumentOut, status_code=201)
async def upload_document(
    room_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_room_or_404(room_id, current_user.id, db)
    file_type = _detect_file_type(file.filename)
    if not file_type:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or XLSX.")

    doc_id = str(uuid.uuid4())
    room_upload_dir = os.path.join(UPLOAD_DIR, room_id)
    os.makedirs(room_upload_dir, exist_ok=True)
    safe_name = f"{doc_id}_{file.filename}"
    file_path = os.path.join(room_upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = models.Document(
        id=doc_id,
        room_id=room_id,
        filename=safe_name,
        original_filename=file.filename,
        file_type=file_type,
        file_size=len(content),
        file_path=file_path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    from database import DATABASE_URL
    background_tasks.add_task(
        _index_in_background, doc_id, room_id, file.filename, file_path, file_type, DATABASE_URL
    )

    log_event(db, room_id, "document_uploaded", {"filename": file.filename, "size": len(content)}, sender_id=current_user.id)
    return doc


@router.get("/{room_id}/documents", response_model=list[schemas.DocumentOut])
def list_documents(
    room_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_room_or_404(room_id, current_user.id, db)
    return db.query(models.Document).filter(models.Document.room_id == room_id).all()


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
    delete_document_from_index(room_id, doc_id)
    db.delete(doc)
    db.commit()
    log_event(db, room_id, "document_deleted", {"filename": doc.original_filename}, sender_id=current_user.id)
