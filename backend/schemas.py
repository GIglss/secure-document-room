from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# Auth
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    token: str
    user: UserOut


# Rooms
class RoomCreate(BaseModel):
    name: str
    description: Optional[str] = None
    expires_at: Optional[datetime] = None


class RoomUpdate(BaseModel):
    status: Optional[str] = None
    expires_at: Optional[datetime] = None
    name: Optional[str] = None
    description: Optional[str] = None


class RoomOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    document_count: Optional[int] = 0
    member_count: Optional[int] = 0

    class Config:
        from_attributes = True


# Documents
class DocumentOut(BaseModel):
    id: str
    room_id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    chunks_count: int
    indexed: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Members
class InviteCreate(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class MemberOut(BaseModel):
    id: str
    room_id: str
    email: str
    name: Optional[str]
    status: str
    invited_at: datetime
    verified_at: Optional[datetime]
    accepted_at: Optional[datetime]

    class Config:
        from_attributes = True


class InviteResult(BaseModel):
    invite_token: str
    invite_link: str
    member: MemberOut


# Join flow
class JoinInfo(BaseModel):
    room_name: str
    description: Optional[str]
    sender_name: str
    status: str
    terms_text: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr


class ConfirmCodeRequest(BaseModel):
    email: EmailStr
    code: str


class AcceptTermsRequest(BaseModel):
    session_token: str


class SessionResponse(BaseModel):
    session_token: str
    room_id: str
    room_name: Optional[str] = None


# Q&A
class QARequest(BaseModel):
    question: str
    session_token: Optional[str] = None


class Citation(BaseModel):
    number: Optional[int] = None
    document_name: str
    page_ref: Optional[str]
    excerpt: str


class QAResponse(BaseModel):
    answer: str
    citations: List[Citation]
    grounded: bool = True
    question_id: Optional[str] = None


# Audit
class AuditEventOut(BaseModel):
    id: int
    room_id: str
    sender_id: Optional[int]
    member_id: Optional[str]
    event_type: str
    event_data: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
