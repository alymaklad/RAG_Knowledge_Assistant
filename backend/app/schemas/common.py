import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import DocStatus, MemberRole, MsgRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    created_at: datetime


class TokenOut(BaseModel):
    """Returned on login for non-browser clients; browsers use the cookies instead."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- courses ---
class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CourseOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    role: MemberRole
    document_count: int = 0
    indexed_count: int = 0
    session_count: int = 0


class MemberIn(BaseModel):
    email: EmailStr
    role: MemberRole = MemberRole.STUDENT


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: MemberRole
    joined_at: datetime


# --- documents ---
class DocumentOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    filename: str
    file_size: int | None
    mime_type: str | None
    page_count: int | None
    chunk_count: int | None
    status: DocStatus
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None


# --- chat ---
class SourceOut(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_name: str
    page_num: int | None
    section_header: str | None = None
    score: float
    text: str


class ChatRequest(BaseModel):
    course_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] | None = None


class SessionOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class MessageOut(ORMModel):
    id: uuid.UUID
    role: MsgRole
    content: str
    source_chunks: list[dict[str, Any]]
    tokens_used: int | None
    created_at: datetime
