import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    rooms = relationship("Room", back_populates="sender")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(String, primary_key=True, default=gen_uuid)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active")  # active | expired | revoked | archived
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sender = relationship("User", back_populates="rooms")
    documents = relationship("Document", back_populates="room", cascade="all, delete-orphan")
    members = relationship("RoomMember", back_populates="room", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="room")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_uuid)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # pdf | docx | xlsx
    file_size = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    scope = Column(String, default="room", nullable=False)  # room | knowledge
    chunks_count = Column(Integer, default=0)
    indexed = Column(Boolean, default=False)
    index_error = Column(Text, nullable=True)  # set if extraction/indexing failed
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="documents")


class RoomMember(Base):
    __tablename__ = "room_members"

    id = Column(String, primary_key=True, default=gen_uuid)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    invite_token = Column(String, unique=True, nullable=False)
    verification_code = Column(String, nullable=True)
    code_expires_at = Column(DateTime, nullable=True)
    verification_attempts = Column(Integer, default=0)
    status = Column(String, default="invited")  # invited | verified | accepted | revoked
    sharing_mode = Column(String, default="anonymized", nullable=False)  # anonymized | full
    session_token = Column(String, nullable=True, unique=True)
    session_expires_at = Column(DateTime, nullable=True)
    invited_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)

    room = relationship("Room", back_populates="members")


class QAInsight(Base):
    """Anonymized analytics row produced after each successful Q&A answer.

    question_text/answer_text are stored ONLY when the member consented with
    sharing_mode="full" at the time the question was asked (snapshot semantics).
    """
    __tablename__ = "qa_insights"

    id = Column(String, primary_key=True, default=gen_uuid)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    member_id = Column(String, ForeignKey("room_members.id"), nullable=True)
    category = Column(String, nullable=False)  # one of insights_service.CATEGORIES
    topic_label = Column(String, nullable=False)  # 3-8 word anonymized label
    sharing_mode = Column(String, nullable=False, default="anonymized")  # snapshot at ask time
    question_text = Column(Text, nullable=True)  # only when sharing_mode == "full"
    answer_text = Column(Text, nullable=True)  # only when sharing_mode == "full"
    created_at = Column(DateTime, default=datetime.utcnow)


class SessionActivity(Base):
    """Lifecycle record for the recipient's session inside the ephemeral sandbox.

    One row per room member. Mirrored (best-effort) to an Azure Table named
    "sessions" so an external cleanup listener can destroy the sandbox when the
    engagement ends or goes idle.
    """
    __tablename__ = "session_activity"

    id = Column(String, primary_key=True, default=gen_uuid)
    member_id = Column(String, ForeignKey("room_members.id"), unique=True, nullable=False)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    sandbox_id = Column(String, nullable=True)
    logged_in_at = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    status = Column(String, default="active", nullable=False)  # active | closed


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    member_id = Column(String, ForeignKey("room_members.id"), nullable=True)
    event_type = Column(String, nullable=False)
    event_data = Column(Text, nullable=True)  # JSON string
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="audit_logs")
