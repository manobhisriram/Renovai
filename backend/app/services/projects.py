from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.models import Lead, Project, RequirementSet
from app.utils.errors import NotFoundError

_PHONE_CLEAN = re.compile(r"[^\d+]")


def normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email and email.strip() else None


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = _PHONE_CLEAN.sub("", phone)
    return cleaned or None


def get_or_create_lead(session: Session, *, name: str, email: str | None, phone: str | None, source: str = "console") -> tuple[Lead, bool]:
    email, phone = normalize_email(email), normalize_phone(phone)
    conds = [c for c in (Lead.email == email if email else None, Lead.phone == phone if phone else None) if c is not None]
    if conds:
        existing = session.scalars(select(Lead).where(or_(*conds))).first()
        if existing:
            return existing, False
    lead = Lead(name=name.strip(), email=email, phone=phone, source=source)
    session.add(lead)
    session.flush()
    return lead, True


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    return project


def is_returning_customer(session: Session, lead: Lead, exclude_project_id: str | None = None) -> bool:
    q = select(func.count(Project.id)).where(Project.lead_id == lead.id)
    if exclude_project_id:
        q = q.where(Project.id != exclude_project_id)
    return bool(session.scalar(q)) or bool(lead.preferences)


def latest_requirements(session: Session, project_id: str) -> dict[str, Any] | None:
    row = session.scalars(select(RequirementSet).where(RequirementSet.project_id == project_id)
                          .order_by(RequirementSet.version.desc())).first()
    return dict(row.data) if row else None


def save_requirements(session: Session, project_id: str, data: dict[str, Any], source: str) -> int:
    current = session.scalar(select(func.max(RequirementSet.version)).where(RequirementSet.project_id == project_id)) or 0
    session.add(RequirementSet(project_id=project_id, version=current + 1, data=data, source=source))
    return int(current + 1)
