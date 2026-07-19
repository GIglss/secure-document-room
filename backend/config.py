"""Centralized configuration and security-critical setting enforcement."""
import os

DEFAULT_SECRET = "dev-secret-key-change-in-production"

# DEV_MODE controls demo conveniences (e.g. returning verification codes in the
# API response). MUST be false in any real deployment.
DEV_MODE = os.getenv("DEV_MODE", "true").lower() in ("1", "true", "yes")

SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET)

# Verification code policy
CODE_TTL_MINUTES = int(os.getenv("CODE_TTL_MINUTES", "10"))
CODE_MAX_ATTEMPTS = int(os.getenv("CODE_MAX_ATTEMPTS", "5"))

# Recipient session policy
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "12"))

# Q&A rate limiting (per accessor, per room)
QA_RATE_MAX = int(os.getenv("QA_RATE_MAX", "15"))
QA_RATE_WINDOW_SECONDS = int(os.getenv("QA_RATE_WINDOW_SECONDS", "60"))

# Upload limits (PDF only)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50 MB
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "200"))

# Ephemeral sandbox identity (optional). When set together with an Azure Tables
# config, recipient session lifecycle is mirrored to the "sessions" table so an
# external listener can destroy the sandbox after the engagement ends.
SANDBOX_ID = os.getenv("SANDBOX_ID", "").strip()

# Password policy (bcrypt hard limit is 72 bytes)
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "8"))


def validate_startup_config():
    """Fail loudly if a production deployment is misconfigured."""
    if not DEV_MODE and SECRET_KEY == DEFAULT_SECRET:
        raise RuntimeError(
            "SECRET_KEY is set to the insecure default while DEV_MODE is off. "
            "Set a strong SECRET_KEY environment variable before deploying."
        )
