"""Serialisation helpers for API responses."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Approval, Lead, Message, Project, ProjectImage, Task, WorkflowEvent, WorkflowRun


def lead_view(lead: Lead) -> dict[str, Any]:
    return {"id": lead.id, "name": lead.name, "email": lead.email, "phone": lead.phone, "source": lead.source, "status": lead.status,
            "notes": lead.notes, "preferences": lead.preferences, "is_sample": lead.is_sample, "created_at": lead.created_at.isoformat()}


def project_view(s: Session, p: Project, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": p.id, "title": p.title, "status": p.status, "category": p.category, "location": p.location, "area_sqm": p.area_sqm,
        "property_type": p.property_type, "request_text": p.request_text, "current_quote_version": p.current_quote_version,
        "summary": p.summary or {}, "suspicious_input": p.suspicious_input, "lead": lead_view(p.lead),
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
        "image_count": int(s.scalar(select(func.count(ProjectImage.id)).where(ProjectImage.project_id == p.id)) or 0),
    }
    if detail:
        pending = s.scalars(select(Approval).where(Approval.project_id == p.id, Approval.status == "pending")).first()
        out["pending_approval"] = approval_view(pending) if pending else None
    return out


def image_view(i: ProjectImage) -> dict[str, Any]:
    return {"id": i.id, "filename": i.original_filename, "content_type": i.content_type, "size_bytes": i.size_bytes,
            "width": i.width, "height": i.height, "created_at": i.created_at.isoformat()}


def approval_view(a: Approval) -> dict[str, Any]:
    return {"id": a.id, "project_id": a.project_id, "quote_id": a.quote_id, "status": a.status, "reasons": a.reasons,
            "requested_at": a.requested_at.isoformat(), "decided_by": a.decided_by,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None, "decision_note": a.decision_note}


def message_view(m: Message) -> dict[str, Any]:
    return {"id": m.id, "role": m.role, "content": m.content, "meta": m.meta, "created_at": m.created_at.isoformat()}


def task_view(t: Task) -> dict[str, Any]:
    return {"id": t.id, "project_id": t.project_id, "lead_id": t.lead_id, "title": t.title, "kind": t.kind, "status": t.status,
            "due_at": t.due_at.isoformat() if t.due_at else None, "assignee": t.assignee, "created_at": t.created_at.isoformat()}


def run_view(r: WorkflowRun) -> dict[str, Any]:
    return {"id": r.id, "mode": r.mode, "status": r.status, "waiting_for": r.waiting_for, "error": r.error,
            "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def event_view(e: WorkflowEvent) -> dict[str, Any]:
    return {"id": e.id, "run_id": e.run_id, "node": e.node, "status": e.status, "summary": e.summary, "detail": e.detail,
            "latency_ms": e.latency_ms, "created_at": e.created_at.isoformat()}
