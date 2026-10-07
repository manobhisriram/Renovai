from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit
from app.database.models import CRMSyncRecord, Lead, Task
from app.schemas.api import LeadPatch, TaskPatch
from app.services.audit import audit
from app.services.container import Container
from app.services.crm_sync import sync_quote
from app.services.views import lead_view, task_view
from app.utils.errors import NotFoundError

router = APIRouter(tags=["crm"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


@router.get("/crm/status")
def crm_status(c: Container = Depends(get_container)) -> dict:
    return {"provider": c.crm.name, "healthy": c.crm.healthy()}


@router.get("/crm/syncs")
def list_syncs(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(CRMSyncRecord).order_by(CRMSyncRecord.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(CRMSyncRecord.status == status)
    return [{"id": r.id, "project_id": r.project_id, "quote_id": r.quote_id, "provider": r.provider, "status": r.status,
             "external_id": r.external_id, "attempts": r.attempts, "last_error": r.last_error, "idempotency_key": r.idempotency_key,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in db.scalars(stmt)]


@router.post("/crm/syncs/{sync_id}/retry")
def retry_sync(sync_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container), user=Depends(current_user)) -> dict:
    rec = db.get(CRMSyncRecord, sync_id)
    if rec is None or rec.quote_id is None:
        raise NotFoundError("Sync record not found.")
    qid = rec.quote_id
    audit(db, user.email, "crm.retry", project_id=rec.project_id)
    db.commit()
    return sync_quote(c.session_factory, c.crm, qid)  # idempotent: a synced record is returned unchanged


@router.get("/leads")
def list_leads(q: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(200)
    if q:
        stmt = stmt.where(Lead.name.ilike(f"%{q[:80]}%"))
    return [lead_view(x) for x in db.scalars(stmt)]


@router.patch("/leads/{lead_id}")
def patch_lead(lead_id: str, body: LeadPatch, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.")
    if body.status:
        lead.status = body.status
    if body.notes is not None:
        lead.notes = body.notes
    audit(db, user.email, "lead.updated", detail={"lead_id": lead_id})
    db.commit()
    return lead_view(lead)


@router.get("/tasks")
def list_tasks(status: str | None = "open", db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Task).order_by(Task.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Task.status == status)
    return [task_view(t) for t in db.scalars(stmt)]


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, db: Session = Depends(get_db)) -> dict:
    t = db.get(Task, task_id)
    if t is None:
        raise NotFoundError("Task not found.")
    t.status = body.status
    db.commit()
    return task_view(t)
