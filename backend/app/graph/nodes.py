"""LangGraph node implementations.

Each node is a small function ``(state) -> partial state``. They are wrapped by ``instrument`` which records a
WorkflowEvent (progress shown in the UI), Prometheus latency, log context, and converts exceptions into
``state['error']`` so one failing step can never corrupt stored project state. Interrupt exceptions pass through.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt
from sqlalchemy import select

from app.agents import chat as chat_agent  # noqa: F401  (re-exported for the chat service)
from app.agents.planning import clarification_questions, classify_project, default_scope, plan_scope, validate_scope
from app.agents.quoting import grounded_amounts, parse_negotiation, recommend, write_narrative
from app.agents.requirements import extract_requirements, normalise_requirements, recompute_missing
from app.categories.registry import PROFILES, TYPICAL_AREA_SQM, get_profile
from app.database.models import ImageAnalysis, Message, ProjectImage, WorkflowEvent, WorkflowRun
from app.llm.safety import scan_injection
from app.observability import metrics
from app.observability.context import node_var, project_id_var, run_id_var
from app.pricing.catalog import TIERS, Catalog
from app.pricing.engine import PricingParams, ScopeInput, determine_complexity, make_params, price_scope
from app.pricing.fitter import fit_to_budget
from app.pricing.timeline import estimate_timeline
from app.schemas.ai import Requirements
from app.services import approvals as approvals_svc
from app.services.audit import audit
from app.services.projects import get_project, is_returning_customer, latest_requirements, save_requirements
from app.services.quotes import DISCLAIMER
from app.tools.registry import ToolContext
from app.utils.errors import AppError, LLMOutputError
from app.vision.analyzer import merge_room_facts
from app.vision.images import to_llm_image  # noqa: F401

log = logging.getLogger(__name__)
MAX_VISION_IMAGES = 6


class NodeFailure(AppError):
    code = "workflow_step_failed"


def match_groups(phrases: list[str], groups: list[str]) -> set[str]:
    """Match free-text phrases like 'false ceiling' or 'the backsplash' to catalog group keys."""
    found: set[str] = set()
    for phrase in phrases:
        low = re.sub(r"[^a-z ]", " ", phrase.lower())
        words = set(low.split()) | {w.rstrip("s") for w in low.split()}
        for g in groups:
            toks = [t.rstrip("s") for t in g.split("_")]
            if all(t in words for t in toks) or g.replace("_", " ") in low:
                found.add(g)
    return found


class GraphNodes:
    def __init__(self, deps: Any):
        self.d = deps
        self.s = deps.settings

    # ------------------------------------------------------------------ plumbing
    def _tool(self, state: dict[str, Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
        ctx = ToolContext(deps=self.d, project_id=state.get("project_id"))
        res = self.d.tools.execute(name, args, ctx, caller="app")
        if not res.ok:
            raise NodeFailure(f"Internal tool '{name}' failed: {res.error}")
        return res.output or {}

    def _record(self, state: dict[str, Any], node: str, status: str, summary: str, detail: dict[str, Any] | None, ms: int) -> None:
        try:
            with self.d.session_factory() as s:
                s.add(WorkflowEvent(project_id=state["project_id"], run_id=state.get("run_id", "-"), node=node, status=status,
                                    summary=summary[:500], detail=detail or {}, latency_ms=ms))
                s.commit()
        except Exception as exc:  # progress events must never break the workflow
            log.warning("could not record workflow event: %s", type(exc).__name__)

    def instrument(self, name: str, fn: Callable[[dict[str, Any]], dict[str, Any] | None]) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            t_p, t_r, t_n = project_id_var.set(state["project_id"]), run_id_var.set(state.get("run_id", "-")), node_var.set(name)
            start = time.perf_counter()
            try:
                update = dict(fn(state) or {})
                status = update.pop("_event_status", "completed")
                summary = update.pop("_summary", name.replace("_", " ").capitalize())
                detail = update.pop("_detail", None)
                ms = int((time.perf_counter() - start) * 1000)
                metrics.NODE_LATENCY.labels(name, status).observe(ms / 1000)
                self._record(state, name, status, summary, detail, ms)
                return update
            except GraphBubbleUp:
                raise  # interrupts must propagate to LangGraph
            except Exception as exc:
                ms = int((time.perf_counter() - start) * 1000)
                msg = exc.message if isinstance(exc, AppError) else f"Unexpected error in step '{name}'."
                log.exception("workflow node %s failed", name) if not isinstance(exc, AppError) else log.warning("node %s failed: %s", name, msg)
                metrics.NODE_LATENCY.labels(name, "failed").observe(ms / 1000)
                self._record(state, name, "failed", msg, {"error_type": type(exc).__name__}, ms)
                return {"error": msg, "status": "failed"}
            finally:
                project_id_var.reset(t_p)
                run_id_var.reset(t_r)
                node_var.reset(t_n)

        return wrapper

    def _catalog(self) -> Catalog:
        with self.d.session_factory() as s:
            cat = Catalog.from_session(s)
        if cat.is_empty():
            raise NodeFailure("The materials catalog is empty. Run `python -m scripts.seed` or add materials in Settings > Pricing data.")
        return cat

    def _params(self, catalog: Catalog, location: str | None, complexity: str) -> PricingParams:
        return make_params(catalog, location, complexity, contingency_pct=self.s.default_contingency_pct,
                           logistics_pct=self.s.default_logistics_pct, tax_pct=self.s.default_tax_pct, currency=self.s.default_currency)

    def _message(self, project_id: str, content: str, meta: dict[str, Any] | None = None) -> None:
        with self.d.session_factory() as s:
            s.add(Message(project_id=project_id, role="assistant", content=content, meta=meta or {}))
            s.commit()

    # ------------------------------------------------------------------ 1. intake
    def intake(self, state: dict[str, Any]) -> dict[str, Any]:
        pid = state["project_id"]
        with self.d.session_factory() as s:
            project = get_project(s, pid)
            lead = project.lead
            text = project.request_text or ""
            returning = is_returning_customer(s, lead, exclude_project_id=pid)
            suspicious = scan_injection(text)
            project.suspicious_input = bool(suspicious)
            project.status = "analyzing"
            audit(s, state.get("actor", "system"), "workflow.started", project_id=pid, detail={"mode": state.get("mode")})
            email, phone, name = lead.email, lead.phone, lead.name
            s.commit()
        ctx: dict[str, Any] = {"name": name}
        cust = self._tool(state, "customer_lookup", {"email": email, "phone": phone})
        ctx["customer"] = cust
        try:
            crm = self._tool(state, "crm_lookup", {"email": email, "phone": phone})
        except NodeFailure:
            crm = {"found": False, "unavailable": True}
        ctx["crm"] = crm
        # The internal CRM *is* our own leads table, so it trivially "finds" the current lead; only an external CRM
        # contact counts as evidence of an existing relationship.
        external_hit = bool(crm.get("found")) and self.d.crm.name != "internal"
        returning = returning or bool(cust.get("found") and cust.get("previous_projects")) or external_hit
        return {"request_text": text, "returning": returning, "customer_context": ctx, "suspicious": suspicious,
                "_summary": ("Returning customer; " if returning else "New customer; ") + ("input flagged for review." if suspicious else "input screened."),
                "_detail": {"returning": returning, "injection_flags": suspicious}}

    # ------------------------------------------------------------------ 2. vision
    def vision(self, state: dict[str, Any]) -> dict[str, Any]:
        pid = state["project_id"]
        with self.d.session_factory() as s:
            images = list(s.scalars(select(ProjectImage).where(ProjectImage.project_id == pid).order_by(ProjectImage.created_at)))[:MAX_VISION_IMAGES]
            existing = {a.image_id: a for a in s.scalars(select(ImageAnalysis).where(ImageAnalysis.project_id == pid))}
        if not images:
            return {"vision": [], "room_facts": {}, "vision_degraded": None, "_event_status": "skipped",
                    "_summary": "No photos uploaded; continuing from the written request."}
        results: list[dict[str, Any]] = []
        failures = 0
        for img in images:
            if img.id in existing:
                results.append({**existing[img.id].result, "image_id": img.id, "cv": existing[img.id].cv})
                continue
            try:
                data = self.d.storage.get(img.storage_key)
                analysis, cv = self.d.vision.analyze_one(data, user_note=state.get("request_text", ""), filename=img.original_filename)
            except Exception as exc:
                failures += 1
                log.warning("vision failed for image %s: %s", img.id, type(exc).__name__)
                continue
            dumped = analysis.model_dump(mode="json")
            with self.d.session_factory() as s:
                s.add(ImageAnalysis(project_id=pid, image_id=img.id, result=dumped, cv=cv.to_dict(),
                                    model=f"{self.d.provider.name}:{self.d.router.model_for(self.d.router.tier_for('vision_analysis'))}"))
                s.commit()
            results.append({**dumped, "image_id": img.id, "cv": cv.to_dict()})
        degraded = (f"{failures} of {len(images)} photos could not be analysed; continuing with the written request."
                    if failures else None)
        facts = merge_room_facts(results)
        return {"vision": results, "room_facts": facts, "vision_degraded": degraded,
                "_event_status": "completed" if results else "failed",
                "_summary": f"Analysed {len(results)} photo(s)" + (f"; {degraded}" if degraded else "."),
                "_detail": {"images": len(results), "mean_confidence": facts.get("mean_confidence")}}

    # ------------------------------------------------------------------ 3. requirements
    def requirements(self, state: dict[str, Any]) -> dict[str, Any]:
        pid = state["project_id"]
        with self.d.session_factory() as s:
            p = get_project(s, pid)
            known = {k: v for k, v in {"area_sqm": p.area_sqm, "location": p.location, "property_type": p.property_type}.items() if v}
            existing = latest_requirements(s, pid)
        facts = state.get("room_facts") or {}
        req = extract_requirements(self.d.llm, text=state.get("request_text", ""), existing=existing, known=known, vision_summary=facts)
        data = normalise_requirements(req, known=known, category=None, vision_area_hint=facts.get("estimated_area_sqm"))
        with self.d.session_factory() as s:
            version = save_requirements(s, pid, data, "extraction")
            s.commit()
        return {"requirements": data, "_summary": f"Extracted requirements v{version} (confidence {data.get('confidence', 0):.2f}).",
                "_detail": {"missing": data.get("missing_information")}}

    def requirements_merge(self, state: dict[str, Any]) -> dict[str, Any]:
        """Merge a clarification answer or a replan message into the requirements (loop re-entry)."""
        pid, text = state["project_id"], state.get("pending_text", "")
        suspicious = list(dict.fromkeys([*(state.get("suspicious") or []), *scan_injection(text)]))
        facts = state.get("room_facts") or {}
        with self.d.session_factory() as s:
            existing = state.get("requirements") or latest_requirements(s, pid) or {}
            p = get_project(s, pid)
            known = {k: v for k, v in {"area_sqm": p.area_sqm, "location": p.location}.items() if v}
            p.status = "analyzing"
            p.suspicious_input = p.suspicious_input or bool(suspicious)
            s.commit()
        req = extract_requirements(self.d.llm, text=text, existing=existing, known=known, vision_summary=facts)
        merged_in = req.model_dump(mode="json")
        base = dict(existing)
        for k, v in merged_in.items():
            if v not in (None, [], "", {}) and k not in ("missing_information", "confidence", "provenance"):
                base[k] = v
        base["provenance"] = {**(existing.get("provenance") or {}), **{k: pv for k, pv in (merged_in.get("provenance") or {}).items() if merged_in.get(k)}}
        base["confidence"] = max(existing.get("confidence", 0), merged_in.get("confidence", 0))
        data = normalise_requirements(Requirements.model_validate({**base, "missing_information": []}), known=known,
                                      category=state.get("category"), vision_area_hint=facts.get("estimated_area_sqm"))
        source = "clarification" if state.get("mode") != "replan" else "replan"
        with self.d.session_factory() as s:
            version = save_requirements(s, pid, data, source)
            s.commit()
        rounds = state.get("clarification_rounds", 0) + (1 if source == "clarification" else 0)
        return {"requirements": data, "clarification_rounds": rounds, "suspicious": suspicious, "request_text": state.get("request_text", ""),
                "_summary": f"Merged client reply into requirements v{version}.", "_detail": {"missing": data.get("missing_information")}}

    def classify(self, state: dict[str, Any]) -> dict[str, Any]:
        res = classify_project(self.d.llm, text=state.get("request_text", "") + " " + state.get("pending_text", ""), requirements=state["requirements"])
        with self.d.session_factory() as s:
            self._set_project(s, state["project_id"], category=res["category"])
        return {"classification": res, "category": res["category"],
                "_summary": f"Classified as {get_profile(res['category']).label} ({res['source']}, {res['confidence']:.2f}).", "_detail": res}

    @staticmethod
    def _set_project(s: Any, pid: str, **fields: Any) -> None:
        p = get_project(s, pid)
        for k, v in fields.items():
            setattr(p, k, v)
        s.commit()

    # ------------------------------------------------------------------ 4. completeness / clarification loop
    def completeness(self, state: dict[str, Any]) -> dict[str, Any]:
        category = state["category"]
        req = recompute_missing(state["requirements"], category)
        profile = get_profile(category)
        prov = dict(req.get("provenance") or {})
        critical = [f for f in profile.critical_fields
                    if (f == "area_sqm" and not (req.get("area_sqm") and prov.get("area_sqm") == "user_provided")) or (f != "area_sqm" and not req.get(f))]
        rounds = state.get("clarification_rounds", 0)
        update: dict[str, Any] = {"missing_critical": critical, "requirements": req, "area_assumed": None}
        if critical and rounds >= self.s.max_clarification_rounds:
            if "area_sqm" in critical:
                hint = req.get("vision_area_hint_sqm")
                value, source = (float(hint), "photo_estimate") if hint else (TYPICAL_AREA_SQM.get(category, 20.0), "category_typical")
                req["area_sqm"], prov["area_sqm"] = value, "estimated"
                req["provenance"] = prov
                update["area_assumed"] = {"value": value, "source": source}
            update["_summary"] = "Still missing critical details after the allowed questions; proceeding with explicit assumptions."
        elif critical:
            update["_summary"] = f"Missing critical details: {', '.join(critical)}. Asking the client."
        else:
            update["_summary"] = "All critical details present."
        update["_detail"] = {"missing_critical": critical, "round": rounds}
        return update

    def clarify_prepare(self, state: dict[str, Any]) -> dict[str, Any]:
        req = state["requirements"]
        missing = list(dict.fromkeys([*state.get("missing_critical", []), *[m for m in req.get("missing_information", []) if m not in state.get("missing_critical", [])]]))[:5]
        qs = clarification_questions(self.d.llm, missing=missing, requirements=req, vision_area_hint=req.get("vision_area_hint_sqm"))
        pid = state["project_id"]
        with self.d.session_factory() as s:
            self._set_project(s, pid, status="awaiting_clarification")
        self._message(pid, "\n".join(f"- {q}" for q in qs), {"type": "clarification", "questions": qs})
        return {"questions": qs, "_event_status": "waiting", "_summary": f"Waiting for the client: {len(qs)} question(s) sent.", "_detail": {"questions": qs}}

    def clarify_wait(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = interrupt({"type": "clarification", "questions": state.get("questions", [])})
        return {"pending_text": str(answer), "_summary": "Client replied."}

    # ------------------------------------------------------------------ 5. RAG
    def retrieve(self, state: dict[str, Any], *, alternatives: bool = False) -> dict[str, Any]:
        req, category = state["requirements"], state["category"]
        profile = get_profile(category)
        rooms = " ".join(req.get("rooms") or [])
        query = " ".join(x for x in [profile.label, req.get("desired_style"), rooms, req.get("location"), req.get("property_type")] if x)
        if alternatives:
            query = f"value engineering budget alternatives cost saving {query}"
        room = (req.get("rooms") or [None])[0]
        res = self.d.retriever.retrieve(query, preferred={"category": category, "room_type": room, "location": req.get("location")})
        evidence, context, degraded = [e.to_dict() for e in res.evidence], res.context, res.degraded
        cust = (state.get("customer_context") or {}).get("customer") or {}
        email = None
        if state.get("returning"):
            with self.d.session_factory() as s:
                email = get_project(s, state["project_id"]).lead.email
        if email and not alternatives:
            prof = self.d.retriever.retrieve("customer style preferences past projects liked", filters={"doc_type": "customer_profile", "customer_email": email}, top_k=3)
            seen = {e["chunk_id"] for e in evidence}
            evidence += [e.to_dict() for e in prof.evidence if e.chunk_id not in seen]
            context += "\n" + prof.context
        if alternatives:  # keep earlier evidence, add the alternatives
            seen = {e["chunk_id"] for e in state.get("evidence", [])}
            evidence = [*state.get("evidence", []), *[e for e in evidence if e["chunk_id"] not in seen]]
            context = (state.get("evidence_context", "") + "\n" + context)[: self.s.rag_context_max_chars * 2]
        _ = cust
        n_ok = sum(1 for e in evidence if not e["flagged"])
        return {"evidence": evidence, "evidence_context": context, "retrieval_degraded": degraded,
                "_event_status": "completed" if not degraded else "failed",
                "_summary": degraded or f"Retrieved {n_ok} supporting document chunk(s) from the knowledge base.",
                "_detail": {"doc_ids": [e["doc_id"] for e in evidence], "query": query, "ms": res.latency_ms}}

    def retrieve_alternatives(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.retrieve(state, alternatives=True)

    # ------------------------------------------------------------------ 6. scope planning (one node per category)
    def make_planner(self, category_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        profile = PROFILES[category_key]

        def plan(state: dict[str, Any]) -> dict[str, Any]:
            catalog = self._catalog()
            req = state["requirements"]
            area = req.get("area_sqm")
            facts = {k: state.get("room_facts", {}).get(k) for k in ("room_type", "design_style", "issues", "opportunities")}
            ctx = ToolContext(deps=self.d, project_id=state["project_id"])
            flags: list[dict[str, Any]] = []
            meta: dict[str, Any]
            source = "llm"
            try:
                scope = plan_scope(self.d.llm, ctx, profile=profile, requirements=req, vision_facts=facts,
                                   evidence_context=state.get("evidence_context", ""), area_sqm=area, catalog=catalog)
                lines, flags = validate_scope(scope, profile, catalog, area)
                meta = {"assumptions": scope.assumptions, "exclusions": scope.exclusions, "evidence_ids": scope.evidence_ids}
                if not lines:
                    raise LLMOutputError("empty scope after validation")
            except LLMOutputError:
                lines = default_scope(profile, area)
                meta = {"assumptions": ["AI scope output was invalid; category default allowances were used."], "exclusions": [], "evidence_ids": []}
                flags.append({"code": "scope_fallback", "severity": "high", "blocking": True,
                              "message": "The AI scope output was invalid, so category default allowances were used. Review quantities carefully."})
                source = "fallback_defaults"
            meta["source"] = source
            meta["risk_notes"] = list(profile.risk_notes)
            return {"scope": lines, "scope_meta": meta, "scope_flags": flags,
                    "_summary": f"Planned {len(lines)} scope line(s) for {profile.label} ({source}).",
                    "_detail": {"groups": [ln["group"] for ln in lines], "flags": [f["code"] for f in flags]}}

        return plan

    # ------------------------------------------------------------------ 7. deterministic pricing + timeline
    def pricing(self, state: dict[str, Any]) -> dict[str, Any]:
        catalog = self._catalog()
        req, category = state["requirements"], state["category"]
        scope = [ScopeInput(ln["group"], Decimal(str(ln["quantity"])), ln.get("optional", False)) for ln in state["scope"]]
        base_params = self._params(catalog, req.get("location"), "standard")
        std = price_scope(scope, catalog, base_params, "standard")
        est_weeks = estimate_timeline(std.lines, category).weeks
        severities = [i.get("severity", "low") for i in (state.get("room_facts") or {}).get("issues", [])]
        complexity, reasons = determine_complexity(rooms=len(req.get("rooms") or []), constraints=req.get("constraints") or [],
                                                   issue_severities=severities, timeline_weeks=req.get("timeline_weeks"), estimated_weeks=est_weeks)
        params = self._params(catalog, req.get("location"), complexity)
        pricing, timelines = {}, {}
        for tier in TIERS:
            res = price_scope(scope, catalog, params, tier)
            pricing[tier] = res.to_dict()
            timelines[tier] = estimate_timeline(res.lines, category).to_dict()
        return {"pricing": pricing, "timelines": timelines, "selected_tier": "standard", "negotiation": None,
                "complexity": {"level": complexity, "reasons": reasons, "params": pricing["standard"]["params"]},
                "_summary": f"Priced budget/standard/premium: {self.s.default_currency} {pricing['budget']['total']:,.0f} / "
                            f"{pricing['standard']['total']:,.0f} / {pricing['premium']['total']:,.0f} (complexity: {complexity}).",
                "_detail": {"totals": {t: pricing[t]["total"] for t in TIERS}, "region": params.region_key,
                            "warnings": pricing["standard"]["warnings"]}}

    # ------------------------------------------------------------------ revise path
    def negotiation_parse(self, state: dict[str, Any]) -> dict[str, Any]:
        text = state.get("pending_text", "")
        suspicious = list(dict.fromkeys([*(state.get("suspicious") or []), *scan_injection(text)]))
        pricing = state.get("pricing") or {}
        sel = state.get("selected_tier", "standard")
        cur = {"selected_tier": sel, "total": (pricing.get(sel) or {}).get("total"), "currency": self.s.default_currency,
               "client_budget": (state.get("requirements") or {}).get("budget")}
        c = parse_negotiation(self.d.llm, message=text, current=cur)
        with self.d.session_factory() as s:
            self._set_project(s, state["project_id"], status="analyzing")
        return {"negotiation": {"constraint": c.model_dump(mode="json"), "message": text, "steps": [], "achievable": None},
                "suspicious": suspicious, "_summary": "Understood the client's new constraints."
                + (f" Target budget {c.new_budget.currency} {c.new_budget.amount:,.0f}." if c.new_budget else " No budget figure given."),
                "_detail": c.model_dump(mode="json")}

    def negotiation_need_budget(self, state: dict[str, Any]) -> dict[str, Any]:
        pid = state["project_id"]
        self._message(pid, "I can look for savings. What budget would you like to stay within? "
                           "I'll show what can change (materials, scope, phasing) and what the trade-offs are.", {"type": "ask_budget"})
        with self.d.session_factory() as s:
            self._set_project(s, pid, status="awaiting_clarification")
        return {"_summary": "Asked the client for a target budget.", "_event_status": "waiting", "status": "awaiting_budget"}

    def negotiation_refit(self, state: dict[str, Any]) -> dict[str, Any]:
        catalog = self._catalog()
        neg = dict(state["negotiation"])
        c = neg["constraint"]
        budget = c["new_budget"]
        if budget["currency"].upper() != self.s.default_currency.upper():
            raise NodeFailure(f"The new budget is in {budget['currency']} but quotes are in {self.s.default_currency}. Please state the budget in {self.s.default_currency}.")
        groups = [ln["group"] for ln in state["scope"]]
        drop = match_groups(c.get("drop_candidates") or [], groups)
        protect = match_groups(c.get("keep_priorities") or [], groups)
        scope_in = [ScopeInput(ln["group"], Decimal(str(ln["quantity"])), ln.get("optional", False) or ln["group"] in drop)
                    for ln in state["scope"] if ln["group"] not in drop]
        params = self._params(catalog, (state["requirements"]).get("location"), state["complexity"]["level"])
        fit = fit_to_budget(scope_in, catalog, params, Decimal(str(budget["amount"])), category=state["category"], protected=protect)
        res = fit.pricing.to_dict()
        pricing = dict(state["pricing"])
        pricing["fitted"] = {**res, "tier_map": fit.tier_map, "dropped_groups": sorted(set(fit.dropped_groups) | drop),
                             "achievable": fit.achievable, "shortfall": float(fit.shortfall)}
        timelines = dict(state["timelines"])
        timelines["fitted"] = estimate_timeline(fit.pricing.lines, state["category"]).to_dict()
        neg.update({"steps": fit.steps_dict(), "achievable": fit.achievable, "budget": budget["amount"], "protected": sorted(protect),
                    "removed_on_request": sorted(drop), "previous_total": (pricing.get(state.get("selected_tier", "standard")) or {}).get("total"),
                    "shortfall": float(fit.shortfall)})
        req = dict(state["requirements"])
        req["budget"] = {"amount": budget["amount"], "currency": budget["currency"]}
        req.setdefault("provenance", {})["budget"] = "user_provided"
        if c.get("timeline_weeks"):
            req["timeline_weeks"] = c["timeline_weeks"]
        with self.d.session_factory() as s:
            save_requirements(s, state["project_id"], req, "negotiation")
            s.commit()
        msg = (f"Fitted to {self.s.default_currency} {budget['amount']:,.0f}: new total {self.s.default_currency} {res['total']:,.0f}." if fit.achievable
               else f"Could not reach {budget['amount']:,.0f}; the minimum achievable total is {res['total']:,.0f} (short by {float(fit.shortfall):,.0f}).")
        return {"pricing": pricing, "timelines": timelines, "selected_tier": "fitted", "negotiation": neg, "requirements": req,
                "_summary": msg + f" {len(fit.steps)} change(s) applied.", "_detail": {"steps": fit.steps_dict(), "achievable": fit.achievable}}

    # ------------------------------------------------------------------ 8. narrative
    def quote_reasoning(self, state: dict[str, Any]) -> dict[str, Any]:
        profile, pricing, cur = get_profile(state["category"]), state["pricing"], self.s.default_currency
        neg = state.get("negotiation") or {}
        tradeoffs = self._tradeoff_facts(state)
        selected = state.get("selected_tier", "standard")
        ctx = {
            "category_label": profile.label, "currency": cur, "risk_notes": list(profile.risk_notes),
            "pricing": {"budget_total": pricing["budget"]["total"], "standard_total": pricing["standard"]["total"],
                        "premium_total": pricing["premium"]["total"], "selected_tier": selected,
                        "selected_total": pricing[selected]["total"], **({"fitted_total": pricing["fitted"]["total"]} if "fitted" in pricing else {})},
            "timeline_weeks": {t: v["weeks"] for t, v in state["timelines"].items()},
            "scope": [{"group": ln["group"], "quantity": ln["quantity"], "unit": ln["unit"], "optional": ln.get("optional", False)} for ln in state["scope"]],
            "assumptions": self._assumptions(state), "exclusions": (state.get("scope_meta") or {}).get("exclusions", []),
            "evidence": [{"id": e["doc_id"], "title": e["title"], "type": e["doc_type"]} for e in state.get("evidence", []) if not e["flagged"]][:6],
            "negotiation": {"budget": neg.get("budget"), "achievable": neg.get("achievable"), "changes": tradeoffs} if neg else None,
            "requirements": {k: state["requirements"].get(k) for k in ("desired_style", "rooms", "priorities", "must_haves", "location")},
        }
        narrative = write_narrative(self.d.llm, context=ctx, user_message=(neg or {}).get("message"))
        allowed = [t["total"] for t in pricing.values()] + [t["subtotal"] for t in pricing.values()]
        if neg.get("budget"):
            allowed.append(float(neg["budget"]))
        flags: list[dict[str, Any]] = []
        stray = grounded_amounts(narrative, allowed)
        data = narrative.model_dump(mode="json")
        if stray:
            data["summary"] = (f"{profile.label}: estimated {cur} {pricing[selected]['total']:,.0f} for the {selected} option, "
                               "including tax and contingency. Figures are estimates pending a site survey.")
            flags.append({"code": "narrative_unsupported_figure", "severity": "medium", "blocking": False,
                          "message": "The AI narrative mentioned an amount that is not in the computed pricing; it was replaced with a deterministic summary."})
        if not data["assumptions"]:
            data["assumptions"] = ctx["assumptions"][:8]
        if tradeoffs and not data["tradeoffs"]:
            data["tradeoffs"] = tradeoffs
        return {"narrative": data, "scope_flags": [*state.get("scope_flags", []), *flags],
                "_summary": "Wrote the quote explanation and checked every figure against the pricing engine."}

    def _assumptions(self, state: dict[str, Any]) -> list[str]:
        out = list((state.get("scope_meta") or {}).get("assumptions", []))
        if state.get("area_assumed"):
            a = state["area_assumed"]
            out.append(f"Floor area was not confirmed by the client; {a['value']:.1f} sqm was assumed from a {a['source'].replace('_', ' ')}.")
        req = state["requirements"]
        if not req.get("location"):
            out.append("No location given; national-average labour and material rates were used.")
        out.append(f"Region used for pricing: {state['complexity']['params'].get('region', 'default')}; complexity: {state['complexity']['level']}.")
        out.append("Catalog prices are sample/configured rates and exclude appliances, loose furniture and structural changes unless listed.")
        return list(dict.fromkeys(out))

    @staticmethod
    def _tradeoffs_label(g: str) -> str:
        return g.replace("_", " ")

    def _tradeoff_facts(self, state: dict[str, Any]) -> list[str]:
        neg = state.get("negotiation") or {}
        facts = []
        for st in neg.get("steps", []):
            if st["action"] == "downgrade":
                facts.append(f"{self._tradeoffs_label(st['group']).capitalize()}: {st['from_tier']} -> {st['to_tier']} (saves {self.s.default_currency} {st['saving']:,.0f}).")
            else:
                facts.append(f"Optional item removed: {self._tradeoffs_label(st['group'])} (saves {self.s.default_currency} {st['saving']:,.0f}).")
        facts += [f"Removed at the client's request: {self._tradeoffs_label(g)}." for g in neg.get("removed_on_request", [])]
        if neg.get("achievable") is False:
            facts.append(f"The budget could not be fully met; the closest achievable total is {self.s.default_currency} {state['pricing']['fitted']['total']:,.0f}. Consider phasing the work.")
        return facts

    # ------------------------------------------------------------------ 9. validation / risk
    def validate(self, state: dict[str, Any]) -> dict[str, Any]:
        flags = list(state.get("scope_flags", []))
        pricing, sel = state["pricing"], state.get("selected_tier", "standard")
        total = pricing[sel]["total"]
        req = state["requirements"]

        def add(code: str, sev: str, msg: str, blocking: bool = False) -> None:
            flags.append({"code": code, "severity": sev, "blocking": blocking, "message": msg})

        if total <= 0:
            add("zero_total", "high", "The computed total is zero; the scope could not be priced.", True)
        if pricing["standard"]["unpriced_groups"]:
            add("unpriced_groups", "medium", f"No catalog price for: {', '.join(pricing['standard']['unpriced_groups'])}.", False)
        if not (pricing["budget"]["total"] <= pricing["standard"]["total"] <= pricing["premium"]["total"]):
            add("tier_order_anomaly", "medium", "Budget/standard/premium totals are not in ascending order; check catalog prices.", False)
        if state.get("area_assumed"):
            add("area_assumed", "high", "Floor area was assumed, not confirmed by the client.", True)
        if state.get("suspicious"):
            add("prompt_injection_suspected", "high", "Client text matched prompt-injection heuristics.", True)
        if state.get("retrieval_degraded"):
            add("retrieval_degraded", "low", state["retrieval_degraded"], False)
        if state.get("vision_degraded"):
            add("vision_degraded", "low", state["vision_degraded"], False)
        if state["category"] not in PROFILES:
            add("unsupported_category", "high", "Project category is not supported; manual estimation required.", True)
        b = (req.get("budget") or {}).get("amount")
        if b and pricing["standard"]["total"] > b * 1.10 and sel == "standard":
            add("over_budget", "info", f"Standard option exceeds the stated budget by {(pricing['standard']['total'] / b - 1) * 100:.0f}%.", False)
        neg = state.get("negotiation") or {}
        if neg.get("achievable") is False:
            add("budget_not_met", "medium", "The requested budget could not be met even at the lowest options.", False)

        req_conf = float(req.get("confidence", 0.0))
        has_img = bool(state.get("vision"))
        vis_conf = float((state.get("room_facts") or {}).get("mean_confidence", 0.0)) if has_img else 0.5
        n_ev = sum(1 for e in state.get("evidence", []) if not e["flagged"])
        ev_conf = min(1.0, n_ev / 4)
        scope_conf = 0.3 if (state.get("scope_meta") or {}).get("source") == "fallback_defaults" else (0.6 if any(f["code"] == "quantity_outlier" for f in flags) else 1.0)
        conf = 0.35 * req_conf + 0.2 * vis_conf + 0.2 * ev_conf + 0.25 * scope_conf
        if state.get("area_assumed"):
            conf *= 0.8
        conf = round(max(0.0, min(1.0, conf)), 2)
        reasons = approvals_svc.approval_reasons(self.s, total=total, confidence=conf, flags=flags, suspicious=bool(state.get("suspicious")))
        return {"validation": {"flags": flags, "confidence": conf, "approval_reasons": reasons,
                               "checks_run": ["totals", "tier_order", "area", "injection", "retrieval", "vision", "category", "budget", "narrative_figures"]},
                "approval_required": bool(reasons),
                "_summary": f"Validated quote: confidence {conf:.2f}, {len(flags)} flag(s), approval {'required' if reasons else 'not required'}.",
                "_detail": {"flags": [f["code"] for f in flags], "reasons": reasons}}

    # ------------------------------------------------------------------ 10. recommendations
    def recommend(self, state: dict[str, Any]) -> dict[str, Any]:
        facts = state.get("room_facts") or {}
        res = recommend(self.d.llm, context={"category": state["category"], "requirements": {k: state["requirements"].get(k) for k in ("desired_style", "rooms", "priorities", "must_haves")},
                                             "vision": {k: facts.get(k) for k in ("room_type", "design_style", "issues", "opportunities")},
                                             "evidence": [{"title": e["title"], "type": e["doc_type"]} for e in state.get("evidence", []) if not e["flagged"]][:5],
                                             "returning_customer": state.get("returning", False)})
        items = [i.model_dump(mode="json") for i in res.items] if res else []
        return {"recommendations": items, "_summary": f"{len(items)} recommendation(s) prepared." if res else "Recommendations unavailable; skipped.",
                "_event_status": "completed" if res else "skipped"}

    # ------------------------------------------------------------------ 11. persist quote
    def save_quote(self, state: dict[str, Any]) -> dict[str, Any]:
        sel, pricing = state.get("selected_tier", "standard"), state["pricing"]
        mode = state.get("mode", "initial")
        reason = {"initial": "initial", "revise": "negotiation", "replan": "replan"}.get(mode, "initial")
        payload = {
            "category": state["category"], "category_label": get_profile(state["category"]).label,
            "options": {t: {**pricing[t], "timeline": state["timelines"][t]} for t in pricing},
            "narrative": state["narrative"], "assumptions": state["narrative"].get("assumptions", []),
            "exclusions": state["narrative"].get("exclusions", []), "risks": state["narrative"].get("risks", []),
            "tradeoffs": state["narrative"].get("tradeoffs", []), "validation": state["validation"],
            "evidence": state.get("evidence", []), "negotiation": state.get("negotiation"),
            "recommendations": state.get("recommendations", []), "scope": state["scope"], "scope_meta": state.get("scope_meta", {}),
            "pricing_params": state["complexity"], "requirements_snapshot": state["requirements"],
            "room_facts": state.get("room_facts", {}), "disclaimer": DISCLAIMER,
            "ai": {"provider": self.d.provider.name, "mock": self.d.provider.name == "mock", "models": self.d.router.describe()["models"]},
        }
        out = self._tool(state, "quote_store", {"project_id": state["project_id"], "payload": payload, "reason": reason, "selected_tier": sel,
                                                "currency": self.s.default_currency, "total": pricing[sel]["total"], "confidence": state["validation"]["confidence"]})
        with self.d.session_factory() as s:
            p = get_project(s, state["project_id"])
            p.summary = {**(p.summary or {}), "category": state["category"], "total": pricing[sel]["total"], "currency": self.s.default_currency,
                         "confidence": state["validation"]["confidence"], "quote_version": out["version"], "selected_tier": sel,
                         "flags": len(state["validation"]["flags"]), "mock_ai": self.d.provider.name == "mock"}
            s.commit()
        return {"quote_id": out["quote_id"], "quote_version": out["version"],
                "_summary": f"Saved quote v{out['version']} ({reason}).", "_detail": {"version": out["version"], "total": pricing[sel]["total"]}}

    # ------------------------------------------------------------------ 12. CRM prepare (read-only)
    def crm_prepare(self, state: dict[str, Any]) -> dict[str, Any]:
        crm = (state.get("customer_context") or {}).get("crm") or {}
        return {"crm": {"provider": self.d.crm.name, "existing_contact": bool(crm.get("found")), "status": "ready_to_sync_after_approval"},
                "_summary": f"CRM ({self.d.crm.name}) prepared; the lead will be written only after approval."}

    # ------------------------------------------------------------------ 13. approval gate
    def approval_decide(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("approval_required"):
            return {"_summary": "Human approval required.", "_detail": {"reasons": state["validation"]["approval_reasons"]}}
        with self.d.session_factory() as s:
            from app.database.models import Quote

            q, p = s.get(Quote, state["quote_id"]), get_project(s, state["project_id"])
            assert q is not None
            q.status, p.status = "approved", "approved"
            audit(s, "system", "approval.auto", project_id=p.id, detail={"quote_version": q.version})
            s.commit()
        return {"approval_decision": {"decision": "approved", "by": "system", "note": "Auto-approved by policy."}, "_summary": "Auto-approved by policy (below thresholds)."}

    def approval_request(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.d.session_factory() as s:
            from app.database.models import Quote

            q, p = s.get(Quote, state["quote_id"]), get_project(s, state["project_id"])
            assert q is not None
            ap = approvals_svc.create_pending(s, p, q, state["validation"]["approval_reasons"])
            s.commit()
            approval_id, title = ap.id, p.title
        to = self.s.notify_reviewer_email
        if to:
            self._tool(state, "notify", {"to": to, "subject": f"Quote awaiting approval: {title}",
                                         "body": f"Project '{title}' quote v{state['quote_version']} needs review.\nReasons:\n- " + "\n- ".join(state["validation"]["approval_reasons"])})
        return {"approval_id": approval_id, "_event_status": "waiting", "_summary": "Quote is waiting for human approval.",
                "_detail": {"approval_id": approval_id, "reasons": state["validation"]["approval_reasons"]}}

    def approval_wait(self, state: dict[str, Any]) -> dict[str, Any]:
        decision = interrupt({"type": "approval", "approval_id": state["approval_id"]})
        return {"approval_decision": dict(decision), "_summary": f"Reviewer decision: {decision.get('decision')}."}

    def approval_apply(self, state: dict[str, Any]) -> dict[str, Any]:
        d = state["approval_decision"]
        with self.d.session_factory() as s:
            approvals_svc.apply_decision(s, state["approval_id"], decision=d["decision"], decided_by=d.get("by", "reviewer"),
                                         note=d.get("note"), selected_tier=d.get("selected_tier"))
            s.commit()
        return {"selected_tier": d.get("selected_tier") or state.get("selected_tier", "standard"),
                "_summary": f"Recorded decision: {d['decision']}."}

    # ------------------------------------------------------------------ 14. CRM write + finalize
    def crm_sync(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            rec = self._tool(state, "crm_create_lead", {"quote_id": state["quote_id"]})
        except NodeFailure as exc:  # a CRM problem must never undo an approval or fail the run
            rec = {"status": "failed", "provider": self.d.crm.name, "last_error": exc.message, "id": None}
        return {"crm": {**state.get("crm", {}), **rec}, "_event_status": "completed" if rec["status"] == "synced" else "failed",
                "_summary": f"CRM sync {rec['status']} ({rec['provider']})" + (f": {rec['last_error']}" if rec.get("last_error") else "."),
                "_detail": rec}

    def finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        pid = state["project_id"]
        decision = (state.get("approval_decision") or {}).get("decision", "approved")
        with self.d.session_factory() as s:
            p = get_project(s, pid)
            p.status = decision
            run = s.get(WorkflowRun, state.get("run_id", ""))
            if run:
                run.waiting_for = None
            audit(s, "system", "workflow.completed", project_id=pid, detail={"decision": decision, "quote_version": state.get("quote_version")})
            s.commit()
        if decision == "approved":
            self._message(pid, f"Your quote (version {state.get('quote_version')}) has been approved. Our team will follow up shortly.", {"type": "quote_approved"})
        else:
            self._message(pid, "The quote was not approved as drafted. Tell us what to change (budget, scope or materials) and we will revise it.", {"type": "quote_rejected"})
        return {"status": decision, "_summary": f"Workflow finished: quote {decision}."}
