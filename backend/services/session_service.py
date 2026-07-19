"""Recipient session lifecycle signals for the ephemeral-sandbox cleanup listener.

The recipient's engagement runs inside a disposable sandbox (identified by the
SANDBOX_ID env var). This module keeps one SessionActivity row per room member
up to date locally, and — when Azure Tables is configured AND SANDBOX_ID is set
— mirrors it to an Azure Table named "sessions" (PartitionKey="sandbox",
RowKey=SANDBOX_ID) so an external listener can decide when to destroy the
sandbox.

Everything here is best-effort: a lifecycle-signal failure must never break a
user-facing request, so all Azure errors are logged and swallowed.
"""
import os
import time
from datetime import datetime

from sqlalchemy.orm import Session

import models

# Throttle: don't rewrite last_activity more than once per member per window.
ACTIVITY_WRITE_INTERVAL_SECONDS = 60
_last_activity_write: dict[str, float] = {}


def _sandbox_id() -> str:
    return os.getenv("SANDBOX_ID", "").strip()


def _get_table_client():
    """Return the Azure "sessions" table client, or None when not configured.

    Reuses the same configuration pattern as the insights mirror
    (services/insights_service.py)."""
    endpoint = os.getenv("AZURE_TABLES_ENDPOINT", "").strip()
    conn_str = os.getenv("AZURE_TABLES_CONNECTION_STRING", "").strip()
    if not endpoint and not conn_str:
        return None
    from azure.data.tables import TableServiceClient

    if conn_str:
        service = TableServiceClient.from_connection_string(conn_str)
    else:
        from azure.identity import DefaultAzureCredential

        service = TableServiceClient(endpoint=endpoint, credential=DefaultAzureCredential())
    return service.create_table_if_not_exists("sessions")


def _mirror_to_azure_table(record: models.SessionActivity):
    """Upsert the session record to the Azure "sessions" table.

    Skipped silently when Azure Tables is not configured or SANDBOX_ID is unset
    (there is no sandbox to clean up in that case)."""
    sandbox_id = _sandbox_id()
    if not sandbox_id:
        return
    try:
        table = _get_table_client()
        if table is None:
            return
        entity = {
            "PartitionKey": "sandbox",
            "RowKey": sandbox_id,
            "sandbox_id": sandbox_id,
            "room_id": record.room_id,
            "logged_in_at": record.logged_in_at.isoformat() if record.logged_in_at else "",
            "last_activity": record.last_activity.isoformat() if record.last_activity else "",
            "status": record.status or "active",
        }
        table.upsert_entity(entity)
    except Exception as e:
        print(f"Azure Tables sessions mirror failed (sandbox {sandbox_id}): {e}")


def _get_or_create_record(db: Session, member: models.RoomMember) -> models.SessionActivity:
    record = (
        db.query(models.SessionActivity)
        .filter(models.SessionActivity.member_id == member.id)
        .first()
    )
    if not record:
        record = models.SessionActivity(
            member_id=member.id,
            room_id=member.room_id,
            sandbox_id=_sandbox_id() or None,
        )
        db.add(record)
    return record


def record_login(db: Session, member: models.RoomMember):
    """Called when the recipient accepts terms and enters the room."""
    try:
        now = datetime.utcnow()
        record = _get_or_create_record(db, member)
        record.logged_in_at = now
        record.last_activity = now
        record.status = "active"
        record.sandbox_id = _sandbox_id() or record.sandbox_id
        db.commit()
        _last_activity_write[member.id] = time.monotonic()
        _mirror_to_azure_table(record)
    except Exception as e:
        db.rollback()
        print(f"Session login record failed for member {member.id}: {e}")


def touch_activity(db: Session, member: models.RoomMember):
    """Called on every authenticated recipient request.

    Writes are throttled to at most one per ACTIVITY_WRITE_INTERVAL_SECONDS per
    member so hot paths (Q&A) don't pay a DB+Azure write on every request."""
    now_mono = time.monotonic()
    last = _last_activity_write.get(member.id)
    if last is not None and (now_mono - last) < ACTIVITY_WRITE_INTERVAL_SECONDS:
        return
    _last_activity_write[member.id] = now_mono
    try:
        record = _get_or_create_record(db, member)
        record.last_activity = datetime.utcnow()
        if record.status != "closed":
            record.status = "active"
        db.commit()
        _mirror_to_azure_table(record)
    except Exception as e:
        db.rollback()
        print(f"Session activity update failed for member {member.id}: {e}")


def close_session(db: Session, member: models.RoomMember):
    """Called when the recipient explicitly ends the session (or the page is
    closed). Marks the session closed — the external listener may then destroy
    the sandbox."""
    try:
        record = _get_or_create_record(db, member)
        record.last_activity = datetime.utcnow()
        record.status = "closed"
        db.commit()
        _mirror_to_azure_table(record)
    except Exception as e:
        db.rollback()
        print(f"Session close failed for member {member.id}: {e}")
