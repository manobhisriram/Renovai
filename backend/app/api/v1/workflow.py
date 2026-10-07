from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.quoting import recommend
from app.auth.deps import current_user, get_container, get_db, rate_limit
from app.database.models import Message, Quote, WorkflowEvent, WorkflowRun
from app.graph.builder import INITIAL_PATH, NODE_LABELS
from app.schemas.api import ChatMessage, ClarificationAnswer, ReviseRequest
from app.services import chat as chat_service
from app.services.audit import audit
from app.services.container import Container
from app.services.projects import get_project
from app.services.quotes import get_quote, quote_view
from app.services.views import event_view, message_view, run_view
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed

router = APIRouter(prefix="/projects", tags=["workflow"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


@router.post("/{project_id}/analyze", status_code=202)
def analyze(project_id: str, background: BackgroundTasks, db: Session = Depends(get_db), c: Container = Depends(get_container),
            user=Depends(current_user)) -> dict:
    p = get_project(db, project_id)
    if not p.request_text.strip() and not p.images:
        raise ValidationFailed("Add a description or at least one photo before running the analysis.")
    waiting = c.workflow.waiting_run(project_id)
    if waiting:
        kind = (waiting.waiting_for or {}).get("type", "input")
        raise ConflictError(f"This project is waiting for {kind.replace('_', ' ')}. Respond to it, or cancel the workflow to start over.")
    run_id = c.workflow.start(project_id, mode="initial", actor=user.email)
    background.add_task(c.workflow.run_new, run_id, project_id, mode="initial", actor=user.email)
    return {"run_id": run_id, "status": "running"}


@router.post("/{project_id}/workflow/cancel")
def cancel_workflow(project_id: str, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    from app.database import utcnow
    from app.utils.errors import AppError  # noqa: F401

    p = get_project(db, project_id)
    n = 0
    for run in db.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.status == "waiting")):
        run.status, run.error, run.waiting_for, run.finished_at = "failed", "Cancelled by user.", None, utcnow()
        n += 1
    if p.status in ("awaiting_clarification", "awaiting_approval") and not p.current_quote_version:
        p.status = "draft"
    audit(db, user.email, "workflow.cancelled", project_id=project_id)
    db.commit()
    return {"cancelled_runs": n}


@router.get("/{project_id}/workflow")
def workflow_status(project_id: str, db: Session = Depends(get_db)) -> dict:
    p = get_project(db, project_id)
    run = db.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id).order_by(WorkflowRun.started_at.desc())).first()
    events = []
    if run:
        events = list(db.scalars(select(WorkflowEvent).where(WorkflowEvent.run_id == run.id).order_by(WorkflowEvent.created_at)))
    return {"project_status": p.status, "run": run_view(run) if run else None, "events": [event_view(e) for e in events],
            "steps": [{"node": n, "label": NODE_LABELS.get(n, n)} for n in INITIAL_PATH],
            "labels": NODE_LABELS}


@router.post("/{project_id}/clarifications", status_code=202)
def answer_clarification(project_id: str, body: ClarificationAnswer, background: BackgroundTasks, db: Session = Depends(get_db),
                         c: Container = Depends(get_container), user=Depends(current_user)) -> dict:
    get_project(db, project_id)
    run_id = c.workflow.prepare_resume(project_id, "clarification")
    db.add(Message(project_id=project_id, role="user", content=body.answer, meta={"type": "clarification_answer"}))
    audit(db, user.email, "clarification.answered", project_id=project_id)
    db.commit()
    background.add_task(c.workflow.run_resume, run_id, project_id, body.answer)
    return {"run_id": run_id, "status": "running"}


@router.get("/{project_id}/messages")
def list_messages(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, project_id)
    return [message_view(m) for m in db.scalars(select(Message).where(Message.project_id == project_id).order_by(Message.created_at))]


@router.post("/{project_id}/messages", status_code=202)
def post_message(project_id: str, body: ChatMessage, background: BackgroundTasks, db: Session = Depends(get_db),
                 c: Container = Depends(get_container), user=Depends(current_user)) -> dict:
    p = get_project(db, project_id)
    return chat_service.handle_message(c, db, p, user.email, body.content, background)


@router.post("/{project_id}/suggestions")
def suggestions(project_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    p = get_project(db, project_id)
    q = db.scalars(select(Quote).where(Quote.project_id == project_id).order_by(Quote.version.desc())).first()
    ctx: dict[str, Any] = {"category": p.category, "request": p.request_text[:600]}
    if q:
        req = q.payload.get("requirements_snapshot") or {}
        ctx.update({"requirements": {k: req.get(k) for k in ("desired_style", "rooms", "priorities", "must_haves")}, "vision": q.payload.get("room_facts", {})})
    res = recommend(c.llm, context=ctx)
    return {"items": [i.model_dump(mode="json") for i in res.items] if res else [], "available": res is not None}


# ----------------------------------------------------------------------------- quotes
@router.get("/{project_id}/quotes")
def list_quotes(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, project_id)
    rows = db.scalars(select(Quote).where(Quote.project_id == project_id).order_by(Quote.version.desc()))
    return [{k: v for k, v in quote_view(q).items() if k != "payload"} | {"summary": (q.payload.get("narrative") or {}).get("summary")} for q in rows]


@router.get("/{project_id}/quotes/{version}")
def read_quote(project_id: str, version: int, db: Session = Depends(get_db)) -> dict:
    get_project(db, project_id)
    return quote_view(get_quote(db, project_id, version))


@router.post("/{project_id}/quotes/revise", status_code=202)
def revise_quote(project_id: str, body: ReviseRequest, background: BackgroundTasks, db: Session = Depends(get_db),
                 c: Container = Depends(get_container), user=Depends(current_user)) -> dict:
    p = get_project(db, project_id)
    if p.current_quote_version == 0:
        raise NotFoundError("There is no quote to revise yet. Run the analysis first.")
    if not body.budget and not body.message:
        raise ValidationFailed("Provide a target budget or a message describing the change.")
    text = body.message or ""
    if body.budget:
        text = f"My budget is {body.budget:,.0f} rupees. {text}".strip()
    run_id = c.workflow.start(project_id, mode="revise", actor=user.email)
    db.add(Message(project_id=project_id, role="user", content=text, meta={"type": "revision_request"}))
    db.commit()
    background.add_task(c.workflow.run_new, run_id, project_id, mode="revise", actor=user.email, pending_text=text)
    return {"run_id": run_id, "status": "running"}
