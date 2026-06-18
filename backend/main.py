import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
import config
from routes import auth, rooms, documents, invites, join, qa, audit

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_startup_config()
    Base.metadata.create_all(bind=engine)
    os.makedirs(os.getenv("UPLOAD_DIR", "./uploads"), exist_ok=True)
    os.makedirs(os.getenv("CHROMA_DIR", "./data/chroma"), exist_ok=True)
    print(f"Secure Document Room API started (DEV_MODE={config.DEV_MODE})")
    yield


app = FastAPI(
    title="Secure Document Room API",
    description="Sealed AI-powered document room for two-party sensitive document sharing",
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
