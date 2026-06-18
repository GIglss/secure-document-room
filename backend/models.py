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
    chunks_count = Column(Integer, default=0)
    indexed = Column(Boolean, default=False)
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
    session_token = Column(String, nullable=True, unique=True)
    session_expires_at = Column(DateTime, nullable=True)
    invited_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)

    room = relationship("Room", back_populates="members")


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
