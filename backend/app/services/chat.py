"""Conversation dispatcher: classifies a client message and routes it to the right workflow action."""

from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import chat as chat_agent
from app.agents.quoting import recommend
from app.database.models import Message, Project, Quote
from app.llm.safety import scan_injection
from app.services.audit import audit
from app.services.container import Container
from app.services.quotes import quote_view


def _facts(db: Session, project: Project) -> dict[str, Any]:
    q = db.scalars(select(Quote).where(Quote.project_id == project.id).order_by(Quote.version.desc())).first()
    facts: dict[str, Any] = {"project_status": project.status, "category": project.category, "title": project.title}
    if q:
        v = quote_view(q)
        facts["quote"] = {"version": v["version"], "status": v["status"], "currency": v["currency"], "selected_tier": v["selected_tier"],
                          "totals": {t: o["total"] for t, o in v["payload"]["options"].items()},
                          "timeline_weeks": {t: o["timeline"]["weeks"] for t, o in v["payload"]["options"].items()},
                          "assumptions": v["payload"].get("assumptions", [])[:6], "exclusions": v["payload"].get("exclusions", [])[:6]}
    return facts


def handle_message(c: Container, db: Session, project: Project, actor: str, content: str, background: BackgroundTasks) -> dict[str, Any]:
    db.add(Message(project_id=project.id, role="user", content=content))
    if scan_injection(content):
        project.suspicious_input = True
        audit(db, actor, "input.injection_suspected", project_id=project.id, detail={"where": "chat"})
    db.commit()

    wf = c.workflow
    waiting_clar = wf.waiting_run(project.id, "clarification")
    has_quote = project.current_quote_version > 0
    intent = chat_agent.classify_intent(c.llm, message=content, awaiting_clarification=waiting_clar is not None, has_quote=has_quote).intent
    if waiting_clar is not None:
        intent = "clarification_answer"

    def reply(text: str, action: str, run_id: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        db.add(Message(project_id=project.id, role="assistant", content=text, meta={"intent": intent, "action": action, **(meta or {})}))
        db.commit()
        return {"intent": intent, "action": action, "reply": text, "run_id": run_id}

    if intent == "clarification_answer":
        run_id = wf.prepare_resume(project.id, "clarification")
        background.add_task(wf.run_resume, run_id, project.id, content)
        return reply("Thanks, I'm updating the requirements and continuing the estimate.", "clarification_resumed", run_id)
    if intent in ("negotiate", "replan") and not has_quote:
        return reply("There is no quote yet. Run the analysis first, then we can adjust it.", "no_quote")
    if intent in ("negotiate", "replan"):
        mode = "revise" if intent == "negotiate" else "replan"
        run_id = wf.start(project.id, mode=mode, actor=actor)
        background.add_task(wf.run_new, run_id, project.id, mode=mode, actor=actor, pending_text=content)
        text = ("Understood. I'm re-fitting the quote to your constraint and will show exactly what changes."
                if mode == "revise" else "Understood. I'm updating the scope and re-running the estimate.")
        return reply(text, f"{mode}_started", run_id)
    if intent == "suggest":
        reqs = None
        qv = db.scalars(select(Quote).where(Quote.project_id == project.id).order_by(Quote.version.desc())).first()
        ctx: dict[str, Any] = {"category": project.category, "request": project.request_text[:600]}
        if qv:
            reqs = qv.payload.get("requirements_snapshot")
            ctx["requirements"] = {k: (reqs or {}).get(k) for k in ("desired_style", "rooms", "priorities", "must_haves")}
            ctx["vision"] = qv.payload.get("room_facts", {})
            ctx["evidence"] = [{"title": e["title"], "type": e["doc_type"]} for e in qv.payload.get("evidence", [])[:5] if not e.get("flagged")]
        recs = recommend(c.llm, context=ctx)
        if recs is None or not recs.items:
            return reply("I couldn't generate suggestions just now. Tell me the room, your style and budget and I'll try again.", "suggestions_unavailable")
        text = "Here are some ideas:\n" + "\n".join(f"- {i.title}: {i.detail}" for i in recs.items)
        return reply(text, "suggestions", meta={"items": [i.model_dump(mode="json") for i in recs.items]})
    if intent == "visualize":
        avail = c.settings.viz_provider != "none"
        return reply("Use the Visualization panel to generate an illustrative render of this room." if avail else
                     "Image generation is not configured on this server, so I can't render visuals yet.", "visualize_hint")
    if intent == "question" and has_quote:
        answer = chat_agent.answer_question(c.llm, message=content, facts=_facts(db, project))
        return reply(answer, "answer")
    return reply("Noted. Tell me if you want to adjust the budget, change the scope, or see ideas.", "ack")
