from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Project, Quote
from app.observability import metrics
from app.utils.errors import NotFoundError

DISCLAIMER = ("This is an estimate prepared with AI assistance from photos and the information provided. Final pricing is "
              "subject to an on-site survey and written approval. It is not a guaranteed price or a construction drawing.")


def next_version(session: Session, project_id: str) -> int:
    return int(session.scalar(select(func.max(Quote.version)).where(Quote.project_id == project_id)) or 0) + 1


def create_quote_version(session: Session, *, project: Project, payload: dict[str, Any], reason: str, selected_tier: str,
                         currency: str, total: float, confidence: float, status: str = "draft") -> Quote:
    """Insert a NEW immutable version. Previous versions are never edited except to mark them superseded."""
    version = next_version(session, project.id)
    parent = version - 1 if version > 1 else None
    for old in session.scalars(select(Quote).where(Quote.project_id == project.id, Quote.status.in_(["draft", "pending_approval"]))):
        old.status = "superseded"
    quote = Quote(project_id=project.id, version=version, parent_version=parent, reason=reason, status=status,
                  selected_tier=selected_tier, currency=currency, total=total, payload=payload, confidence=confidence)
    session.add(quote)
    project.current_quote_version = version
    session.flush()
    metrics.QUOTES_CREATED.labels(reason).inc()
    return quote


def get_quote(session: Session, project_id: str, version: int) -> Quote:
    q = session.scalars(select(Quote).where(Quote.project_id == project_id, Quote.version == version)).first()
    if q is None:
        raise NotFoundError("Quote version not found.")
    return q


def quote_view(q: Quote) -> dict[str, Any]:
    return {"id": q.id, "project_id": q.project_id, "version": q.version, "parent_version": q.parent_version,
            "reason": q.reason, "status": q.status, "selected_tier": q.selected_tier, "currency": q.currency,
            "total": float(q.total), "confidence": q.confidence, "created_at": q.created_at.isoformat(),
            "payload": q.payload}
