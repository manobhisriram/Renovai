from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import utcnow
from app.database.models import Approval, Project, Quote
from app.observability import metrics
from app.services.audit import audit
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed


def approval_reasons(settings: Settings, *, total: float, confidence: float, flags: list[dict[str, Any]], suspicious: bool) -> list[str]:
    """Configurable policy deciding whether a human must approve. Returns the reasons (empty = no approval needed)."""
    reasons: list[str] = []
    if settings.approval_require_always:
        reasons.append("Policy: every quote requires human approval.")
    if total > settings.approval_total_threshold:
        reasons.append(f"Quote total exceeds the approval threshold ({settings.approval_total_threshold:,.0f}).")
    if confidence < settings.approval_min_confidence:
        reasons.append(f"Overall confidence {confidence:.2f} is below the minimum {settings.approval_min_confidence:.2f}.")
    if suspicious:
        reasons.append("Input matched prompt-injection heuristics; a person must review.")
    for f in flags:
        if f.get("blocking"):
            reasons.append(f["message"])
    return list(dict.fromkeys(reasons))


def create_pending(session: Session, project: Project, quote: Quote, reasons: list[str]) -> Approval:
    for old in session.scalars(select(Approval).where(Approval.project_id == project.id, Approval.status == "pending")):
        old.status = "rejected"
        old.decision_note = "Superseded by a newer quote version."
        old.decided_at = utcnow()
    quote.status = "pending_approval"
    approval = Approval(project_id=project.id, quote_id=quote.id, reasons=reasons)
    session.add(approval)
    project.status = "awaiting_approval"
    session.flush()
    audit(session, "system", "approval.requested", project_id=project.id, detail={"quote_version": quote.version, "reasons": reasons})
    return approval


def apply_decision(session: Session, approval_id: str, *, decision: str, decided_by: str, note: str | None,
                   selected_tier: str | None) -> tuple[Approval, Quote, Project]:
    """Single place that records an approval decision. Idempotent-safe: a decided approval cannot be re-decided."""
    if decision not in ("approved", "rejected"):
        raise ValidationFailed("decision must be 'approved' or 'rejected'.")
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise NotFoundError("Approval not found.")
    if approval.status != "pending":
        raise ConflictError(f"This approval was already {approval.status}.")
    quote, project = session.get(Quote, approval.quote_id), session.get(Project, approval.project_id)
    assert quote is not None and project is not None
    if selected_tier:
        if selected_tier not in quote.payload.get("options", {}):
            raise ValidationFailed(f"Quote v{quote.version} has no '{selected_tier}' option.")
        quote.selected_tier = selected_tier
        quote.total = quote.payload["options"][selected_tier]["total"]
    approval.status, approval.decided_by, approval.decided_at, approval.decision_note = decision, decided_by, utcnow(), note
    quote.status = decision
    project.status = decision
    audit(session, decided_by, f"approval.{decision}", project_id=project.id,
          detail={"quote_version": quote.version, "tier": quote.selected_tier, "note": note})
    metrics.APPROVALS.labels(decision).inc()
    session.flush()
    return approval, quote, project
