"""HTTP request/response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: dict[str, Any]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "reviewer", "sales"] = "sales"


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=32)


class ProjectCreate(BaseModel):
    lead: LeadIn
    title: str = Field(min_length=1, max_length=255)
    request_text: str = Field("", max_length=4000)
    property_type: str | None = Field(None, max_length=64)
    location: str | None = Field(None, max_length=128)
    area_sqm: float | None = Field(None, gt=0, le=5000)


class RequirementsPatch(BaseModel):
    """Staff edits. Everything set here is recorded with provenance 'user_provided'."""

    area_sqm: float | None = Field(None, gt=0, le=5000)
    location: str | None = Field(None, max_length=128)
    desired_style: str | None = Field(None, max_length=64)
    budget_amount: float | None = Field(None, gt=0)
    timeline_weeks: float | None = Field(None, gt=0, le=260)
    rooms: list[str] | None = None
    must_haves: list[str] | None = None


class ClarificationAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ReviseRequest(BaseModel):
    budget: float | None = Field(None, gt=0)
    message: str = Field("", max_length=2000)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=2000)
    selected_tier: Literal["budget", "standard", "premium", "fitted"] | None = None


class FeedbackIn(BaseModel):
    step: str = Field(max_length=64)
    rating: Literal[1, -1]
    comment: str | None = Field(None, max_length=1000)


class RagSearch(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    doc_type: str | None = None
    category: str | None = None
    top_k: int = Field(6, ge=1, le=20)


class VisualizationRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=600)
    image_id: str | None = None


class MaterialUpdate(BaseModel):
    unit_price: float | None = Field(None, ge=0)
    available: bool | None = None
    lead_days: int | None = Field(None, ge=0, le=365)


class LeadPatch(BaseModel):
    status: Literal["new", "contacted", "quoted", "won", "lost"] | None = None
    notes: str | None = Field(None, max_length=4000)


class TaskPatch(BaseModel):
    status: Literal["open", "done"]
