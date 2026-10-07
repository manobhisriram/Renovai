"""LangGraph state. Everything here must be JSON-serialisable (it is checkpointed)."""

from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    # control
    project_id: str
    run_id: str
    mode: str  # initial | revise | replan
    actor: str
    pending_text: str
    error: str | None
    status: str
    # intake
    request_text: str
    returning: bool
    customer_context: dict[str, Any]
    suspicious: list[str]
    # perception
    vision: list[dict[str, Any]]
    room_facts: dict[str, Any]
    vision_degraded: str | None
    # understanding
    requirements: dict[str, Any]
    classification: dict[str, Any]
    category: str
    missing_critical: list[str]
    clarification_rounds: int
    questions: list[str]
    area_assumed: dict[str, Any] | None
    # knowledge
    evidence: list[dict[str, Any]]
    evidence_context: str
    retrieval_degraded: str | None
    # scope + money
    scope: list[dict[str, Any]]
    scope_meta: dict[str, Any]
    scope_flags: list[dict[str, Any]]
    pricing: dict[str, Any]
    timelines: dict[str, Any]
    complexity: dict[str, Any]
    selected_tier: str
    negotiation: dict[str, Any] | None
    # narrative / checks
    narrative: dict[str, Any]
    validation: dict[str, Any]
    recommendations: list[dict[str, Any]]
    # persistence / integration
    quote_id: str
    quote_version: int
    crm: dict[str, Any]
    approval_id: str
    approval_required: bool
    approval_decision: dict[str, Any]
