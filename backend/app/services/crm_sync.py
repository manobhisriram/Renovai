"""Idempotent CRM synchronisation. Never raises: failures become retryable records + a follow-up task.

Three short phases so no database transaction is ever held open across an external call:
  1. record the attempt (commit)  2. call the CRM provider  3. record the outcome (commit)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.crm.base import CRMLeadPayload, CRMProvider
from app.database import SessionFactory, utcnow
from app.database.models import CRMSyncRecord, Lead, Project, Quote, Task
from app.observability import metrics
from app.services.audit import audit
from app.utils.resilience import retry_call

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _build_payload(project: Project, lead: Lead, quote: Quote, key: str) -> CRMLeadPayload:
    req = quote.payload.get("requirements_snapshot") or {}
    option = (quote.payload.get("options") or {}).get(quote.selected_tier, {})
    return CRMLeadPayload(
        idempotency_key=key, project_id=project.id, name=lead.name, email=lead.email, phone=lead.phone,
        project_title=project.title, category=project.category, budget=(req.get("budget") or {}).get("amount"),
        quote_total=float(quote.total), currency=quote.currency, quote_version=quote.version, selected_tier=quote.selected_tier,
        timeline_weeks=(option.get("timeline") or {}).get("weeks"),
        follow_up_date=(utcnow() + timedelta(days=2)).date().isoformat(), status="quoted", notes="Approved quote ready for follow-up.")


def sync_quote(session_factory: SessionFactory, crm: CRMProvider, quote_id: str) -> dict[str, Any]:
    # Phase 1: load, dedupe, record the attempt.
    with session_factory() as s:
        quote = s.get(Quote, quote_id)
        assert quote is not None
        project = s.get(Project, quote.project_id)
        assert project is not None
        lead = s.get(Lead, project.lead_id)
        assert lead is not None
        key = f"{project.id}:v{quote.version}"
        rec = s.scalars(select(CRMSyncRecord).where(CRMSyncRecord.idempotency_key == key)).first()
        if rec and rec.status == "synced":
            return _view(rec)  # duplicate prevention: this version was already written
        payload = _build_payload(project, lead, quote, key)
        if rec is None:
            rec = CRMSyncRecord(project_id=project.id, quote_id=quote.id, provider=crm.name, idempotency_key=key, payload=payload.to_dict(), attempts=0, status="pending")
            s.add(rec)
        rec.attempts += 1
        s.commit()
        rec_id, project_id, lead_id, lead_name = rec.id, project.id, lead.id, lead.name

    # Phase 2: external call, no transaction open.
    error: str | None = None
    external_id: str | None = None
    try:
        result = retry_call(lambda: crm.upsert_lead(payload), attempts=MAX_ATTEMPTS, base_delay=0.5)
        external_id = result.external_id
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        log.warning("CRM sync failed for project %s: %s", project_id, type(exc).__name__)

    # Phase 3: record the outcome.
    with session_factory() as s:
        rec = s.get(CRMSyncRecord, rec_id)
        assert rec is not None
        if error is None:
            rec.status, rec.external_id, rec.last_error = "synced", external_id, None
            metrics.CRM_SYNCS.labels(crm.name, "synced").inc()
            audit(s, "system", "crm.synced", project_id=project_id, detail={"provider": crm.name, "external_id": external_id})
        else:
            rec.status, rec.last_error = "failed", error
            metrics.CRM_SYNCS.labels(crm.name, "failed").inc()
            s.add(Task(project_id=project_id, lead_id=lead_id, kind="crm_sync_failed",
                       title=f"CRM sync failed for {lead_name} - retry or enter manually", due_at=utcnow() + timedelta(days=1)))
            audit(s, "system", "crm.failed", project_id=project_id, detail={"provider": crm.name, "error": error})
        s.commit()
        return _view(rec)


def _view(rec: CRMSyncRecord) -> dict[str, Any]:
    return {"id": rec.id, "project_id": rec.project_id, "quote_id": rec.quote_id, "provider": rec.provider, "status": rec.status,
            "external_id": rec.external_id, "attempts": rec.attempts, "last_error": rec.last_error,
            "idempotency_key": rec.idempotency_key, "updated_at": rec.updated_at.isoformat() if rec.updated_at else None}
