"""Workflow runtime: durable checkpointing, run lifecycle, resume and state hydration."""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from typing import Any, cast

from langgraph.types import Command
from sqlalchemy import select

from app.config import Settings
from app.database import utcnow
from app.database.models import Project, Quote, WorkflowRun
from app.graph.builder import build_graph
from app.observability.context import project_id_var, run_id_var
from app.services.audit import audit
from app.services.projects import get_project
from app.utils.errors import AppError, ConflictError, NotFoundError

log = logging.getLogger(__name__)
STALE_RUN_MINUTES = 30


def build_checkpointer(settings: Settings) -> Any:
    backend = settings.resolved_checkpoint_backend
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver(sqlite3.connect(settings.graph_checkpoint_sqlite_path, check_same_thread=False))
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    pool = ConnectionPool(conninfo=url, max_size=5, open=True, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(cast(Any, pool))
    saver.setup()
    return saver


class WorkflowService:
    def __init__(self, deps: Any, checkpointer: Any | None = None):
        self.d = deps
        self._checkpointer = checkpointer
        self._graph: Any = None

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._checkpointer = self._checkpointer or build_checkpointer(self.d.settings)
            self._graph = build_graph(self.d, self._checkpointer)
        return self._graph

    @staticmethod
    def _cfg(project_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": project_id}, "recursion_limit": 80}

    # ------------------------------------------------------------------ lifecycle
    def recover_stale_runs(self) -> int:
        """Runs left 'running' by a crashed process are marked failed so the project can be retried."""
        cutoff = utcnow() - timedelta(minutes=STALE_RUN_MINUTES)
        n = 0
        with self.d.session_factory() as s:
            for run in s.scalars(select(WorkflowRun).where(WorkflowRun.status == "running")):
                started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=cutoff.tzinfo)
                if started < cutoff:
                    run.status, run.error, run.finished_at = "failed", "Interrupted by a server restart.", utcnow()
                    n += 1
            s.commit()
        return n

    def start(self, project_id: str, *, mode: str, actor: str) -> str:
        """Create a run row (fails if one is already active for this project)."""
        with self.d.session_factory() as s:
            get_project(s, project_id)
            active = s.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.status == "running")).first()
            if active:
                raise ConflictError("An analysis is already running for this project. Wait for it to finish.")
            run = WorkflowRun(project_id=project_id, mode=mode, status="running")
            s.add(run)
            audit(s, actor, f"workflow.{mode}.requested", project_id=project_id)
            s.commit()
            return run.id

    def waiting_run(self, project_id: str, kind: str | None = None) -> WorkflowRun | None:
        with self.d.session_factory() as s:
            q = select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.status == "waiting").order_by(WorkflowRun.started_at.desc())
            for run in s.scalars(q):
                if kind is None or (run.waiting_for or {}).get("type") == kind:
                    s.expunge(run)
                    return run
        return None

    def prepare_resume(self, project_id: str, kind: str) -> str:
        """Flip the waiting run back to 'running' and return its id."""
        with self.d.session_factory() as s:
            run = None
            for r in s.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id, WorkflowRun.status == "waiting").order_by(WorkflowRun.started_at.desc())):
                if (r.waiting_for or {}).get("type") == kind:
                    run = r
                    break
            if run is None:
                raise NotFoundError(f"Nothing is waiting for a {kind.replace('_', ' ')} on this project.")
            run.status, run.waiting_for = "running", None
            s.commit()
            return run.id

    # ------------------------------------------------------------------ execution (blocking; call from a worker thread)
    def run_new(self, run_id: str, project_id: str, *, mode: str, actor: str, pending_text: str | None = None) -> None:
        if mode in ("revise", "replan"):
            try:
                self._ensure_state_for_reentry(project_id)
            except Exception as exc:  # pre-flight failure: never leave the run row stuck in 'running'
                self._fail_run(run_id, project_id, exc)
                return
        graph_input: dict[str, Any] = {"project_id": project_id, "run_id": run_id, "mode": mode, "actor": actor, "error": None, "status": "running",
                                       "pending_text": pending_text or ""}
        if mode == "initial":
            graph_input.update({"clarification_rounds": 0, "questions": [], "negotiation": None, "approval_required": False,
                                "approval_decision": {}, "area_assumed": None})
        self._invoke(run_id, project_id, graph_input)

    def run_resume(self, run_id: str, project_id: str, value: Any) -> None:
        self._invoke(run_id, project_id, Command(resume=value))

    def _invoke(self, run_id: str, project_id: str, graph_input: Any) -> None:
        tp, tr = project_id_var.set(project_id), run_id_var.set(run_id)
        cfg = self._cfg(project_id)
        try:
            result = self.graph.invoke(graph_input, cfg)
            snap = self.graph.get_state(cfg)
            waiting = [i.value for t in snap.tasks for i in t.interrupts]
            with self.d.session_factory() as s:
                run = s.get(WorkflowRun, run_id)
                assert run is not None
                if waiting:
                    run.status, run.waiting_for = "waiting", waiting[0]
                elif result.get("error"):
                    run.status, run.error, run.finished_at = "failed", str(result["error"])[:500], utcnow()
                    project = get_project(s, project_id)
                    if project.status not in ("approved", "rejected"):  # never undo a recorded decision
                        project.status = "failed"
                else:
                    run.status, run.finished_at = "completed", utcnow()
                s.commit()
        except Exception as exc:
            self._fail_run(run_id, project_id, exc)
        finally:
            project_id_var.reset(tp)
            run_id_var.reset(tr)


    def _fail_run(self, run_id: str, project_id: str, exc: Exception) -> None:
        if isinstance(exc, AppError):
            log.warning("workflow run %s failed: %s", run_id, exc.message)
        else:
            log.exception("workflow run %s crashed", run_id)
        msg = exc.message if isinstance(exc, AppError) else "The analysis stopped unexpectedly. Try again."
        with self.d.session_factory() as s:
            run = s.get(WorkflowRun, run_id)
            if run:
                run.status, run.error, run.finished_at, run.waiting_for = "failed", msg[:500], utcnow(), None
            p = s.get(Project, project_id)
            if p and p.status not in ("approved", "rejected") and p.current_quote_version == 0:
                p.status = "failed"
            s.commit()

    # ------------------------------------------------------------------ state hydration
    def _ensure_state_for_reentry(self, project_id: str) -> None:
        cfg = self._cfg(project_id)
        values = self.graph.get_state(cfg).values or {}
        if values.get("scope") and values.get("pricing") and values.get("requirements"):
            return
        with self.d.session_factory() as s:
            q = s.scalars(select(Quote).where(Quote.project_id == project_id).order_by(Quote.version.desc())).first()
            if q is None:
                raise ConflictError("There is no quote to revise yet. Run the analysis first.")
            payload = dict(q.payload)
            version, qid, sel = q.version, q.id, q.selected_tier
        options = payload["options"]
        hydrated = {
            "project_id": project_id, "category": payload["category"], "requirements": payload["requirements_snapshot"],
            "scope": payload["scope"], "scope_meta": payload.get("scope_meta", {}), "scope_flags": [],
            "complexity": payload["pricing_params"],
            "pricing": {t: {k: v for k, v in o.items() if k != "timeline"} for t, o in options.items()},
            "timelines": {t: o["timeline"] for t, o in options.items()}, "selected_tier": sel,
            "evidence": payload.get("evidence", []), "evidence_context": "", "validation": payload.get("validation", {}),
            "narrative": payload.get("narrative", {}), "quote_id": qid, "quote_version": version, "room_facts": payload.get("room_facts", {}),
            "returning": False, "customer_context": {}, "suspicious": [], "vision": [], "negotiation": payload.get("negotiation"),
        }
        self.graph.update_state(cfg, hydrated, as_node="finalize")
        log.info("rehydrated workflow state for project %s from quote v%s", project_id, version)

    # ------------------------------------------------------------------ introspection
    def snapshot(self, project_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(self._cfg(project_id))
        v = snap.values or {}
        return {"next": list(snap.next), "has_state": bool(v), "category": v.get("category")}
