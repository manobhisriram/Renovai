from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit, require_roles
from app.database.models import Approval, Project, Quote
from app.schemas.api import ApprovalDecision
from app.services import approvals as svc
from app.services.audit import audit
from app.services.container import Container
from app.services.crm_sync import sync_quote
from app.services.views import approval_view
from app.utils.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


@router.get("")
def list_approvals(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Approval).order_by(Approval.requested_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Approval.status == status)
    out = []
    for a in db.scalars(stmt):
        q, p = db.get(Quote, a.quote_id), db.get(Project, a.project_id)
        out.append({**approval_view(a), "project_title": p.title if p else None, "quote_version": q.version if q else None,
                    "quote_total": float(q.total) if q else None, "currency": q.currency if q else None, "selected_tier": q.selected_tier if q else None,
                    "confidence": q.confidence if q else None})
    return out


@router.post("/{approval_id}/decision", status_code=202)
def decide(approval_id: str, body: ApprovalDecision, background: BackgroundTasks, db: Session = Depends(get_db),
           c: Container = Depends(get_container), user=Depends(require_roles("admin", "reviewer"))) -> dict:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise NotFoundError("Approval not found.")
    if approval.status != "pending":
        raise ConflictError(f"This approval was already {approval.status}.")
    q = db.get(Quote, approval.quote_id)
    if body.selected_tier and q and body.selected_tier not in q.payload.get("options", {}):
        raise ConflictError(f"Quote v{q.version} has no '{body.selected_tier}' option.")
    wf = c.workflow
    waiting = wf.waiting_run(approval.project_id, "approval")
    if waiting is not None and (waiting.waiting_for or {}).get("approval_id") == approval_id:
        run_id = wf.prepare_resume(approval.project_id, "approval")
        background.add_task(wf.run_resume, run_id, approval.project_id,
                            {"decision": body.decision, "by": user.email, "note": body.note, "selected_tier": body.selected_tier})
        return {"status": "processing", "run_id": run_id}
    # No live workflow thread (e.g. checkpoint store was reset): record the decision directly and still sync the CRM.
    _, quote, _p = svc.apply_decision(db, approval_id, decision=body.decision, decided_by=user.email, note=body.note, selected_tier=body.selected_tier)
    audit(db, "system", "approval.applied_without_graph", project_id=approval.project_id)
    db.commit()
    if body.decision == "approved":
        background.add_task(sync_quote, c.session_factory, c.crm, quote.id)
    return {"status": "recorded", "run_id": None}
