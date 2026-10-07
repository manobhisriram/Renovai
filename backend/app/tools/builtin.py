"""Concrete tools. Model-callable tools are read-only; anything that writes is ``llm_exposed=False``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.categories.registry import get_profile
from app.config import Settings
from app.database.models import Lead, Project
from app.pricing.catalog import Catalog
from app.pricing.engine import ScopeInput, make_params, price_scope
from app.pricing.timeline import estimate_timeline
from app.services.projects import normalize_email, normalize_phone
from app.tools.registry import ToolContext, ToolDef, ToolRegistry

TierName = Literal["budget", "standard", "premium"]


# ---------------------------------------------------------------- model-callable (read-only)
class MaterialLookupIn(BaseModel):
    group: str = Field(description="Material group key, e.g. 'kitchen_cabinets'")
    tier: TierName | None = None


def material_lookup(ctx: ToolContext, a: MaterialLookupIn) -> dict[str, Any]:
    with ctx.deps.session_factory() as s:
        cat = Catalog.from_session(s)
    tiers = [a.tier] if a.tier else ["budget", "standard", "premium"]
    options = []
    for t in tiers:
        item = cat.item(a.group, t)
        if item:
            options.append({"sku": item.sku, "name": item.name, "tier": t, "unit": item.unit,
                            "base_unit_price": float(item.unit_price), "currency": item.currency, "lead_days": item.lead_days,
                            "note": "Base price before regional/complexity adjustments. Final prices are computed by the application."})
    return {"group": a.group, "available": bool(options), "options": options}


class LaborIn(BaseModel):
    group: str
    quantity: float = Field(gt=0, le=100000)
    tier: TierName = "standard"


def labor_estimation(ctx: ToolContext, a: LaborIn) -> dict[str, Any]:
    with ctx.deps.session_factory() as s:
        cat = Catalog.from_session(s)
    item = cat.item_or_nearest(a.group, a.tier)
    if item is None:
        return {"group": a.group, "available": False}
    hours = float(item.labor_hours_per_unit) * a.quantity
    rate = cat.labor_rate(item.labor_trade) or Decimal("0")
    return {"group": a.group, "trade": item.labor_trade, "labor_hours": round(hours, 1), "hourly_rate": float(rate),
            "base_labor_cost": round(hours * float(rate), 2)}


class RegionIn(BaseModel):
    location: str | None = None


def regional_multiplier(ctx: ToolContext, a: RegionIn) -> dict[str, Any]:
    with ctx.deps.session_factory() as s:
        cat = Catalog.from_session(s)
    r = cat.resolve_region(a.location)
    return {"region": r.key if r else "default", "multiplier": float(r.multiplier) if r else 1.0,
            "matched": bool(r and r.key != "default")}


class LineIn(BaseModel):
    group: str
    quantity: float = Field(gt=0, le=100000)


class TimelineIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=40)
    category: str = "general_interior_renovation"
    tier: TierName = "standard"


def _priced(ctx: ToolContext, lines: list[LineIn], tier: str, location: str | None, complexity: str) -> Any:
    s_: Settings = ctx.deps.settings
    with ctx.deps.session_factory() as s:
        cat = Catalog.from_session(s)
    params = make_params(cat, location, complexity, contingency_pct=s_.default_contingency_pct,
                         logistics_pct=s_.default_logistics_pct, tax_pct=s_.default_tax_pct, currency=s_.default_currency)
    return price_scope([ScopeInput(x.group, Decimal(str(x.quantity))) for x in lines], cat, params, tier)


def timeline_estimation(ctx: ToolContext, a: TimelineIn) -> dict[str, Any]:
    res = _priced(ctx, a.lines, a.tier, None, "standard")
    return estimate_timeline(res.lines, a.category).to_dict()


class PricingIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=40)
    tier: TierName = "standard"
    location: str | None = None
    complexity: Literal["low", "standard", "high", "rush"] = "standard"


def pricing_calculation(ctx: ToolContext, a: PricingIn) -> dict[str, Any]:
    res = _priced(ctx, a.lines, a.tier, a.location, a.complexity).to_dict()
    return {k: res[k] for k in ("tier_label", "materials_subtotal", "labor_subtotal", "logistics", "subtotal", "contingency",
                                "tax", "total", "currency", "warnings")}


class SimilarityIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    category: str | None = None
    room_type: str | None = None
    doc_type: str | None = Field(None, description="past_project | historical_quote | material | policy | design_guideline | faq")


def project_similarity_search(ctx: ToolContext, a: SimilarityIn) -> dict[str, Any]:
    res = ctx.deps.retriever.retrieve(a.query, filters={"doc_type": a.doc_type, "category": a.category} if (a.doc_type or a.category) else None,
                                      preferred={"category": a.category, "room_type": a.room_type}, top_k=4)
    if res.degraded:
        return {"available": False, "reason": res.degraded, "results": []}
    return {"available": True, "results": [
        {"doc_id": e.doc_id, "title": e.title, "doc_type": e.doc_type, "score": round(e.score, 3), "snippet": e.snippet[:300]}
        for e in res.evidence if not e.flagged]}


# ---------------------------------------------------------------- application-only
class CustomerLookupIn(BaseModel):
    email: str | None = None
    phone: str | None = None


def customer_lookup(ctx: ToolContext, a: CustomerLookupIn) -> dict[str, Any]:
    email, phone = normalize_email(a.email), normalize_phone(a.phone)
    conds = [c for c in (Lead.email == email if email else None, Lead.phone == phone if phone else None) if c is not None]
    if not conds:
        return {"found": False}
    with ctx.deps.session_factory() as s:
        lead = s.scalars(select(Lead).where(or_(*conds)).order_by(Lead.created_at)).first()
        if lead is None:
            return {"found": False}
        others = list(s.scalars(select(Project).where(Project.lead_id == lead.id, Project.id != (ctx.project_id or ""))))
        return {"found": True, "lead_id": lead.id, "name": lead.name, "status": lead.status, "preferences": lead.preferences,
                "previous_projects": [{"id": p.id, "title": p.title, "category": p.category, "status": p.status} for p in others]}


def crm_lookup(ctx: ToolContext, a: CustomerLookupIn) -> dict[str, Any]:
    c = ctx.deps.crm.lookup_contact(email=a.email, phone=a.phone)
    return {"found": False} if c is None else {"found": True, "external_id": c.external_id, "name": c.name, "properties": c.properties}


class CrmCreateIn(BaseModel):
    quote_id: str


def crm_create_lead(ctx: ToolContext, a: CrmCreateIn) -> dict[str, Any]:
    from app.services.crm_sync import sync_quote

    return sync_quote(ctx.deps.session_factory, ctx.deps.crm, a.quote_id)


class QuoteStoreIn(BaseModel):
    project_id: str
    payload: dict[str, Any]
    reason: Literal["initial", "negotiation", "replan"]
    selected_tier: str
    currency: str
    total: float
    confidence: float


def quote_store(ctx: ToolContext, a: QuoteStoreIn) -> dict[str, Any]:
    from app.services.audit import audit
    from app.services.projects import get_project
    from app.services.quotes import create_quote_version

    with ctx.deps.session_factory() as s:
        project = get_project(s, a.project_id)
        q = create_quote_version(s, project=project, payload=a.payload, reason=a.reason, selected_tier=a.selected_tier,
                                 currency=a.currency, total=a.total, confidence=a.confidence)
        audit(s, "system", "quote.created", project_id=project.id, detail={"version": q.version, "reason": a.reason, "total": a.total})
        s.commit()
        return {"quote_id": q.id, "version": q.version}


class ProjectStoreIn(BaseModel):
    project_id: str
    status: str | None = None
    category: str | None = None
    summary: dict[str, Any] | None = None
    suspicious_input: bool | None = None


def project_store(ctx: ToolContext, a: ProjectStoreIn) -> dict[str, Any]:
    from app.services.projects import get_project

    with ctx.deps.session_factory() as s:
        p = get_project(s, a.project_id)
        if a.status:
            p.status = a.status
        if a.category:
            p.category = a.category
        if a.summary is not None:
            p.summary = {**(p.summary or {}), **a.summary}
        if a.suspicious_input is not None:
            p.suspicious_input = a.suspicious_input
        s.commit()
        return {"ok": True, "status": p.status}


class NotifyIn(BaseModel):
    to: str
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)


def notify(ctx: ToolContext, a: NotifyIn) -> dict[str, Any]:
    return {"sent": ctx.deps.notifier.send(a.to, a.subject, a.body)}


def build_tool_registry(settings: Settings) -> ToolRegistry:
    reg = ToolRegistry(default_timeout_s=settings.tool_timeout_seconds)
    model_tools: list[tuple[str, str, Any, Any]] = [
        ("material_lookup", "Look up available catalog options (and BASE unit prices) for a material group.", MaterialLookupIn, material_lookup),
        ("labor_estimation", "Estimate labour hours for a quantity of a material group.", LaborIn, labor_estimation),
        ("regional_multiplier", "Get the regional cost multiplier for a city/location.", RegionIn, regional_multiplier),
        ("timeline_estimation", "Estimate programme length (weeks) for a set of scope lines.", TimelineIn, timeline_estimation),
        ("pricing_calculation", "Compute a deterministic price for scope lines (what-if). Use for sanity checks only.", PricingIn, pricing_calculation),
        ("project_similarity_search", "Search the knowledge base (past projects, quotes, materials, policies) for similar work.", SimilarityIn, project_similarity_search),
    ]
    for name, desc, model, fn in model_tools:
        reg.register(ToolDef(name, desc, model, fn, llm_exposed=True))
    app_tools: list[tuple[str, str, Any, Any, bool]] = [
        ("customer_lookup", "Find an existing customer in the application database.", CustomerLookupIn, customer_lookup, False),
        ("crm_lookup", "Find a contact in the configured CRM.", CustomerLookupIn, crm_lookup, False),
        ("crm_create_lead", "Write an approved quote to the CRM (idempotent).", CrmCreateIn, crm_create_lead, True),
        ("quote_store", "Persist a new immutable quote version.", QuoteStoreIn, quote_store, True),
        ("project_store", "Update project status/summary.", ProjectStoreIn, project_store, True),
        ("notify", "Send a notification e-mail (or log it when SMTP is not configured).", NotifyIn, notify, True),
    ]
    for name, desc, model, fn, side in app_tools:
        reg.register(ToolDef(name, desc, model, fn, llm_exposed=False, side_effect=side, timeout_s=60 if name == "crm_create_lead" else None))
    return reg


__all__ = ["build_tool_registry", "get_profile"]
