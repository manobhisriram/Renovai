from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit, require_roles
from app.database import utcnow
from app.database.models import Approval, AuditEvent, CRMSyncRecord, Feedback, LLMCall, Project, Quote, WorkflowRun
from app.services.container import Container

router = APIRouter(tags=["analytics"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


@router.get("/analytics/summary")
def summary(days: int = 30, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    since = utcnow() - timedelta(days=min(max(days, 1), 365))
    by = lambda col: {k: int(v) for k, v in db.execute(select(col, func.count()).group_by(col)).all()}  # noqa: E731
    approved = db.execute(select(func.coalesce(func.sum(Quote.total), 0), func.count()).where(Quote.status == "approved")).one()
    llm_rows = db.execute(select(LLMCall.model, LLMCall.tier, func.count(), func.avg(LLMCall.latency_ms), func.coalesce(func.sum(LLMCall.input_tokens), 0),
                                 func.coalesce(func.sum(LLMCall.output_tokens), 0), func.coalesce(func.sum(LLMCall.est_cost_usd), 0),
                                 func.sum(case((LLMCall.success.is_(False), 1), else_=0)))
                          .where(LLMCall.created_at >= since).group_by(LLMCall.model, LLMCall.tier)).all()
    fb = db.execute(select(func.coalesce(func.sum(Feedback.rating), 0), func.count()).where(Feedback.created_at >= since)).one()
    durations = [(r.finished_at - r.started_at).total_seconds() for r in db.scalars(select(WorkflowRun).where(WorkflowRun.status == "completed", WorkflowRun.started_at >= since)) if r.finished_at]
    return {
        "window_days": days, "mock_ai": c.provider.name == "mock",
        "projects_by_status": by(Project.status), "quotes_by_status": by(Quote.status), "approvals_by_status": by(Approval.status),
        "crm_syncs_by_status": by(CRMSyncRecord.status), "approved_value": float(approved[0]), "approved_quotes": int(approved[1]),
        "avg_quote_confidence": round(float(db.scalar(select(func.avg(Quote.confidence))) or 0), 2),
        "avg_workflow_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "llm": [{"model": m, "tier": t, "calls": int(n), "avg_latency_ms": int(lat or 0), "input_tokens": int(i), "output_tokens": int(o),
                 "est_cost_usd": float(cost) if cost else None, "errors": int(e or 0)} for m, t, n, lat, i, o, cost, e in llm_rows],
        "feedback": {"net": int(fb[0]), "count": int(fb[1])},
    }


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db), _=Depends(require_roles("admin"))) -> list[dict]:
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500)))
    return [{"id": e.id, "project_id": e.project_id, "actor": e.actor, "action": e.action, "detail": e.detail,
             "request_id": e.request_id, "created_at": e.created_at.isoformat()} for e in rows]


@router.get("/system/config")
def system_config(c: Container = Depends(get_container)) -> dict:
    s = c.settings
    return {
        "env": s.app_env, "version": s.app_version, "llm": c.router.describe(),
        "mock_ai": c.provider.name == "mock",
        "rag": {"vector_db": "qdrant", "remote": bool(s.qdrant_url), "collection": s.qdrant_collection, "embedder": c.embedder.name},
        "crm": {"provider": c.crm.name}, "storage": s.storage_backend, "visualization": c.viz.name,
        "checkpointing": s.resolved_checkpoint_backend, "redis": bool(s.redis_url),
        "approval": {"always": s.approval_require_always, "total_threshold": s.approval_total_threshold, "min_confidence": s.approval_min_confidence},
        "pricing_defaults": {"currency": s.default_currency, "tax_pct": s.default_tax_pct, "contingency_pct": s.default_contingency_pct,
                             "logistics_pct": s.default_logistics_pct},
        "observability": {"metrics": s.metrics_enabled, "langfuse": bool(s.langfuse_public_key), "otel": bool(s.otel_exporter_otlp_endpoint)},
        "configuration_problems": s.missing_required(),
    }
