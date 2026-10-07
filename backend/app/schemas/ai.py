"""Pydantic schemas for every structured LLM output. These are the contracts the model must satisfy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Provenance = Literal["detected", "estimated", "user_provided", "unknown"]
Tier = Literal["budget", "standard", "premium"]
Severity = Literal["low", "medium", "high"]


class Attribute(BaseModel):
    """A value plus where it came from. The UI renders `provenance` as a badge."""

    value: str | None = None
    provenance: Provenance = "unknown"
    confidence: float = Field(0.0, ge=0, le=1)


class DimensionEstimate(BaseModel):
    """Photo-derived dimensions are ALWAYS estimates; exact measurements need an on-site survey."""

    width_m: float | None = Field(None, ge=0, le=100)
    length_m: float | None = Field(None, ge=0, le=100)
    height_m: float | None = Field(None, ge=0, le=15)
    area_sqm: float | None = Field(None, ge=0, le=5000)
    provenance: Provenance = "estimated"
    confidence: float = Field(0.0, ge=0, le=1)
    basis: str = "visual estimate from photo; not a measurement"


class VisibleIssue(BaseModel):
    description: str = Field(max_length=300)
    severity: Severity = "low"
    confidence: float = Field(0.0, ge=0, le=1)


class RoomVisionAnalysis(BaseModel):
    room_type: Attribute = Field(default_factory=Attribute)
    dimensions: DimensionEstimate = Field(default_factory=DimensionEstimate)
    furniture: list[str] = Field(default_factory=list, max_length=30)
    flooring: Attribute = Field(default_factory=Attribute)
    walls: Attribute = Field(default_factory=Attribute)
    ceiling: Attribute = Field(default_factory=Attribute)
    lighting: Attribute = Field(default_factory=Attribute)
    fixtures: list[str] = Field(default_factory=list, max_length=30)
    visible_issues: list[VisibleIssue] = Field(default_factory=list, max_length=20)
    design_style: Attribute = Field(default_factory=Attribute)
    renovation_opportunities: list[str] = Field(default_factory=list, max_length=15)
    overall_confidence: float = Field(0.0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class Money(BaseModel):
    amount: float = Field(ge=0)
    currency: str = "INR"


class Requirements(BaseModel):
    project_type: str | None = Field(None, description="e.g. renovation, new build, upgrade, redesign")
    property_type: str | None = Field(None, description="e.g. 2BHK apartment, villa, office")
    rooms: list[str] = Field(default_factory=list, max_length=20)
    desired_style: str | None = None
    budget: Money | None = None
    timeline_weeks: float | None = Field(None, ge=0, le=260)
    area_sqm: float | None = Field(None, ge=0, le=5000)
    location: str | None = None
    priorities: list[str] = Field(default_factory=list, max_length=15)
    must_haves: list[str] = Field(default_factory=list, max_length=25)
    optional_items: list[str] = Field(default_factory=list, max_length=25)
    constraints: list[str] = Field(default_factory=list, max_length=15)
    missing_information: list[str] = Field(default_factory=list, max_length=15)
    confidence: float = Field(0.0, ge=0, le=1)
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @field_validator("missing_information", mode="before")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v or []))


class ProjectClassification(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=400)


class ClarificationQuestions(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=4)


class ScopeLine(BaseModel):
    group: str = Field(description="Material group key from the catalog, e.g. 'kitchen_cabinets'")
    quantity: float = Field(gt=0, le=100000)
    unit: str
    optional: bool = False
    rationale: str = Field("", max_length=300)
    quantity_basis: Provenance = "estimated"


class ScopePlan(BaseModel):
    lines: list[ScopeLine] = Field(min_length=1, max_length=40)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    exclusions: list[str] = Field(default_factory=list, max_length=15)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class QuoteNarrative(BaseModel):
    summary: str = Field(max_length=1200)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    exclusions: list[str] = Field(default_factory=list, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=12)
    tradeoffs: list[str] = Field(default_factory=list, max_length=12)


class NegotiationConstraint(BaseModel):
    new_budget: Money | None = None
    timeline_weeks: float | None = Field(None, ge=0, le=260)
    keep_priorities: list[str] = Field(default_factory=list, max_length=10)
    drop_candidates: list[str] = Field(default_factory=list, max_length=10)
    wants_cheaper: bool = False
    notes: str = Field("", max_length=400)


class Recommendation(BaseModel):
    title: str = Field(max_length=120)
    detail: str = Field(max_length=500)
    kind: Literal["design", "material", "upsell", "smart_home", "risk", "other"] = "design"


class Recommendations(BaseModel):
    items: list[Recommendation] = Field(max_length=8)


class ChatIntent(BaseModel):
    intent: Literal["negotiate", "clarification_answer", "replan", "suggest", "visualize", "question", "other"]
    confidence: float = Field(0.0, ge=0, le=1)


class AnswerText(BaseModel):
    answer: str = Field(max_length=1500)
