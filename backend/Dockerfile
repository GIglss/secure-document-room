# Secure Document Room — backend (FastAPI + Chroma RAG)
FROM python:3.12-slim

# uv for fast, lockfile-faithful installs
COPY --from=ghcr.io/astral-sh/uv:0.5.24 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# curl for container healthchecks; build-essential kept out on purpose —
# all pinned deps ship manylinux wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code
COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Persistent state lives in volumes mounted here (see docker-compose.prod.yml):
#   /app/uploads          - raw uploaded documents      (UPLOAD_DIR)
#   /app/data             - Chroma vector DB + SQLite   (CHROMA_DIR, DATABASE_URL)
RUN mkdir -p /app/uploads /app/data/chroma

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
