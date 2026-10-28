"""Request/response models for the HTTP API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["chat", "research", "deep_research"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=32)
    message: str = Field(default="", max_length=20000)
    mode: Literal["chat", "research"] = "chat"
    document_ids: list[str] = Field(default_factory=list, max_length=5)
    regenerate: bool = False


class ResearchRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=32)
    question: str = Field(min_length=3, max_length=8000)
    review_plan: bool = False
    focus: Literal["general", "academic"] = "general"


class PlanApproval(BaseModel):
    subquestions: list[str] = Field(default_factory=list, max_length=7)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    mode: Mode | None = None


class ConversationOut(ORM):
    id: str
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: str
    role: str
    content: str
    mode: str
    provider: str | None
    model: str | None
    status: str
    research_job_id: str | None
    meta: dict[str, Any]
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    active_job_id: str | None = None


class SourceOut(ORM):
    id: str
    number: int
    url: str
    title: str
    domain: str
    published_date: str | None
    retrieved_at: datetime
    snippet: str
    subquestion: str | None
    source_type: str | None
    readable: bool
    error: str | None
    search_provider: str | None


class JobOut(ORM):
    id: str
    conversation_id: str
    question: str
    status: str
    error: str | None
    plan: dict[str, Any] | None
    options: dict[str, Any]
    report_id: str | None
    created_at: datetime


class ReportSummary(ORM):
    id: str
    title: str
    job_id: str | None
    conversation_id: str | None
    created_at: datetime


class ReportOut(ReportSummary):
    markdown: str
    verification: dict[str, Any] | None
    provider: str | None
    sources: list[SourceOut] = Field(default_factory=list)


class DocumentOut(ORM):
    id: str
    filename: str
    size_bytes: int
    page_count: int
    has_text: bool
    status: str
    created_at: datetime
