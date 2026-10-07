from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.database.models import AuditEvent
from app.observability.context import request_id_var


def audit(session: Session, actor: str, action: str, *, project_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    rid = request_id_var.get()
    session.add(AuditEvent(actor=actor, action=action, project_id=project_id, detail=detail or {},
                           request_id=None if rid == "-" else rid))
