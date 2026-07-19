import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import config
from routes import auth, rooms, documents, invites, join, qa, audit, insights, session

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _reindex_pending_documents():
    """Self-heal: re-process any documents left unindexed by a prior crash or an
    older code version. Prints per-document results so failures are never silent
    (the #1 cause of a document stuck on 'Processing…' forever)."""
    from database import SessionLocal
    import models
    from services.document_processor import process_document
    from services.rag_engine import index_document

    db = SessionLocal()
    try:
        pending = db.query(models.Document).filter(models.Document.indexed == False).all()  # noqa: E712
        if not pending:
            return
        print(f"Re-indexing {len(pending)} pending document(s) on startup...")
        for doc in pending:
            try:
                if not os.path.exists(doc.file_path):
                    print(f"  SKIP  {doc.original_filename}: source file missing ({doc.file_path})")
                    continue
                chunks = process_document(doc.file_path, doc.file_type)
                if not chunks:
                    doc.indexed = False
                    doc.chunks_count = 0
                    doc.index_error = "No extractable text found (scanned/image-only PDF?)."
                    db.commit()
                    print(f"  SKIP  {doc.original_filename}: no extractable text")
                    continue
                count = index_document(
                    doc.room_id, doc.id, doc.original_filename, chunks,
                    scope=doc.scope or "room",
                    sender_id=doc.room.sender_id if doc.room else None,
                )
                doc.indexed = True
                doc.chunks_count = count
                doc.index_error = None
                db.commit()
                print(f"  OK    {doc.original_filename} ({count} chunks)")
            except Exception as e:
                db.rollback()
                try:
                    doc.indexed = False
                    doc.index_error = f"{type(e).__name__}: {e}"
                    db.commit()
                except Exception:
                    db.rollback()
                print(f"  FAIL  {doc.original_filename}: {e}")
    finally:
        db.close()


def _auto_migrate():
    """Lightweight additive migrations for SQLite (no Alembic in MVP).
    Adds columns introduced after a DB was first created, so existing
    databases don't break on startup. New tables (e.g. qa_insights) are
    handled by create_all; deleting secure_room.db also recreates everything."""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # (table, column, DDL) — additive only, safe to re-run
    migrations = [
        ("documents", "index_error", "ALTER TABLE documents ADD COLUMN index_error TEXT"),
        ("documents", "scope", "ALTER TABLE documents ADD COLUMN scope TEXT NOT NULL DEFAULT 'room'"),
        ("room_members", "sharing_mode", "ALTER TABLE room_members ADD COLUMN sharing_mode TEXT NOT NULL DEFAULT 'anonymized'"),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            if table not in tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(ddl))
                print(f"Migration: added {table}.{column}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_startup_config()
    Base.metadata.create_all(bind=engine)
    _auto_migrate()
    os.makedirs(os.getenv("UPLOAD_DIR", "./uploads"), exist_ok=True)
    os.makedirs(os.getenv("CHROMA_DIR", "./data/chroma"), exist_ok=True)
    print(f"Secure Document Room API started (DEV_MODE={config.DEV_MODE})")
    # Warm the embedding model once so the first upload doesn't pay the load cost
    # mid-request, and so any model-load failure surfaces loudly at boot.
    try:
        from services.rag_engine import _get_embedding_fn
        _get_embedding_fn()
    except Exception as e:
        print(f"WARNING: embedding model failed to load at startup: {e}")
    try:
        _reindex_pending_documents()
    except Exception as e:
        print(f"Startup re-index skipped: {e}")
    yield


app = FastAPI(
    title="Secure Document Room API",
    description="Secure document room: share and review sensitive documents with AI Q&A powered by a local sovereign model inside an ephemeral sandbox",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router, prefix="/api")
app.include_router(rooms.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(invites.router, prefix="/api")
app.include_router(join.router, prefix="/api")
app.include_router(qa.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(session.router, prefix="/api")


@app.get("/")
def root():
    return {"status": "ok", "service": "Secure Document Room API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/llm-config")
def llm_config():
    """Return active LLM provider and model name (no secrets)."""
    from services.rag_engine import get_llm_config
    return get_llm_config()
