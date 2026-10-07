"""Built-in CRM: the application database is the system of record. Free, always available."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select

from app.crm.base import CRMContact, CRMLeadPayload, CRMWriteResult
from app.database import SessionFactory, utcnow
from app.database.models import Lead, Task


class InternalCRM:
    name = "internal"

    def __init__(self, session_factory: SessionFactory):
        self._sf = session_factory

    def lookup_contact(self, *, email: str | None = None, phone: str | None = None) -> CRMContact | None:
        if not email and not phone:
            return None
        conds = []
        if email:
            conds.append(Lead.email == email.lower())
        if phone:
            conds.append(Lead.phone == phone)
        with self._sf() as s:
            lead = s.scalars(select(Lead).where(or_(*conds)).order_by(Lead.created_at)).first()
            if lead is None:
                return None
            return CRMContact(lead.id, lead.name, lead.email, lead.phone, {"status": lead.status, "preferences": lead.preferences})

    def upsert_lead(self, payload: CRMLeadPayload) -> CRMWriteResult:
        with self._sf() as s:
            from app.database.models import Project

            project = s.get(Project, payload.project_id)
            lead = s.get(Lead, project.lead_id) if project else None
            if lead is None:
                raise LookupError("lead not found for project")
            lead.status = payload.status
            existing = s.scalars(select(Task).where(Task.project_id == payload.project_id, Task.kind == "follow_up", Task.status == "open")).first()
            created = existing is None
            if created:
                s.add(Task(project_id=payload.project_id, lead_id=lead.id, kind="follow_up", assignee=None,
                           title=f"Follow up with {lead.name}: quote v{payload.quote_version} ({payload.currency} {payload.quote_total:,.0f})"
                           if payload.quote_total else f"Follow up with {lead.name}", due_at=utcnow() + timedelta(days=2)))
            s.commit()
            return CRMWriteResult(lead.id, created)

    def healthy(self) -> bool:
        try:
            with self._sf() as s:
                s.execute(select(Lead.id).limit(1))
            return True
        except Exception:
            return False
