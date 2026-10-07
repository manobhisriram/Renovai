"""Deterministic pricing engine.

The LLM may choose *which* materials and *how much*; every currency figure comes from here.

    line   = (qty x unit_price  +  qty x labour_hrs x hourly_rate x complexity) x regional_multiplier
    sub    = sum(lines) + logistics% x materials
    total  = (sub + contingency% x sub) x (1 + tax%)

All amounts use ``Decimal`` and are rounded half-up to 2 places at each reported figure, so the parts
always add up exactly to the total.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.pricing.catalog import Catalog

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
COMPLEXITY_FACTORS = {"low": Decimal("0.90"), "standard": Decimal("1.00"), "high": Decimal("1.20"), "rush": Decimal("1.30")}


def q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricingParams:
    region_key: str = "default"
    region_multiplier: Decimal = Decimal("1.00")
    complexity: str = "standard"
    contingency_pct: Decimal = Decimal("8")
    logistics_pct: Decimal = Decimal("3")
    tax_pct: Decimal = Decimal("18")
    currency: str = "INR"

    @property
    def complexity_factor(self) -> Decimal:
        return COMPLEXITY_FACTORS.get(self.complexity, Decimal("1.00"))


@dataclass(frozen=True)
class ScopeInput:
    group: str
    quantity: Decimal
    optional: bool = False


@dataclass
class PricedLine:
    group: str
    sku: str
    name: str
    tier: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    material_cost: Decimal
    labor_trade: str
    labor_hours: Decimal
    labor_rate: Decimal
    labor_cost: Decimal
    line_total: Decimal
    optional: bool
    lead_days: int


@dataclass
class PricingResult:
    tier_label: str
    tier_map: dict[str, str]
    lines: list[PricedLine]
    materials_subtotal: Decimal
    labor_subtotal: Decimal
    logistics: Decimal
    subtotal: Decimal
    contingency: Decimal
    tax: Decimal
    total: Decimal
    currency: str
    params: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    unpriced_groups: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def conv(o: Any) -> Any:
            if isinstance(o, Decimal):
                return float(o)
            if isinstance(o, dict):
                return {k: conv(v) for k, v in o.items()}
            if isinstance(o, list):
                return [conv(v) for v in o]
            return o

        return conv(asdict(self))


def make_params(catalog: Catalog, location: str | None, complexity: str, *, contingency_pct: float,
                logistics_pct: float, tax_pct: float, currency: str) -> PricingParams:
    region = catalog.resolve_region(location)
    return PricingParams(
        region_key=region.key if region else "default",
        region_multiplier=region.multiplier if region else Decimal("1.00"),
        complexity=complexity,
        contingency_pct=Decimal(str(contingency_pct)),
        logistics_pct=Decimal(str(logistics_pct)),
        tax_pct=Decimal(str(tax_pct)),
        currency=currency,
    )


def price_scope(
    scope: list[ScopeInput],
    catalog: Catalog,
    params: PricingParams,
    tier: str = "standard",
    tier_map: dict[str, str] | None = None,
    *,
    exclude_groups: set[str] | None = None,
    label: str | None = None,
) -> PricingResult:
    """Price ``scope`` using ``tier`` for every group, optionally overridden per group by ``tier_map``."""
    exclude_groups = exclude_groups or set()
    lines: list[PricedLine] = []
    warnings: list[str] = []
    unpriced: list[str] = []
    used_tiers: dict[str, str] = {}
    mult, cplx = params.region_multiplier, params.complexity_factor

    for item in scope:
        if item.group in exclude_groups:
            continue
        if item.quantity <= 0:
            warnings.append(f"Ignored non-positive quantity for '{item.group}'.")
            continue
        wanted = (tier_map or {}).get(item.group, tier)
        mat = catalog.item_or_nearest(item.group, wanted)
        if mat is None:
            unpriced.append(item.group)
            warnings.append(f"No catalog price for '{item.group}'; it is excluded from the total.")
            continue
        if mat.tier != wanted:
            warnings.append(f"'{item.group}' has no {wanted} option; used {mat.tier}.")
        rate = catalog.labor_rate(mat.labor_trade)
        if rate is None:
            warnings.append(f"No labour rate for trade '{mat.labor_trade}'; labour for '{item.group}' priced at 0.")
            rate = Decimal("0")
        hours = item.quantity * mat.labor_hours_per_unit
        material_cost = q(item.quantity * mat.unit_price * mult)
        labor_cost = q(hours * rate * cplx * mult)
        used_tiers[item.group] = mat.tier
        lines.append(PricedLine(
            group=item.group, sku=mat.sku, name=mat.name, tier=mat.tier, unit=mat.unit,
            quantity=item.quantity, unit_price=mat.unit_price, material_cost=material_cost,
            labor_trade=mat.labor_trade, labor_hours=q(hours), labor_rate=rate, labor_cost=labor_cost,
            line_total=material_cost + labor_cost, optional=item.optional, lead_days=mat.lead_days,
        ))

    materials = sum((ln.material_cost for ln in lines), Decimal("0"))
    labor = sum((ln.labor_cost for ln in lines), Decimal("0"))
    logistics = q(materials * params.logistics_pct / HUNDRED)
    subtotal = materials + labor + logistics
    contingency = q(subtotal * params.contingency_pct / HUNDRED)
    taxable = subtotal + contingency
    tax = q(taxable * params.tax_pct / HUNDRED)
    total = taxable + tax
    return PricingResult(
        tier_label=label or tier, tier_map=used_tiers, lines=lines, materials_subtotal=materials,
        labor_subtotal=labor, logistics=logistics, subtotal=subtotal, contingency=contingency, tax=tax,
        total=total, currency=params.currency,
        params={"region": params.region_key, "region_multiplier": float(mult), "complexity": params.complexity,
                "complexity_factor": float(cplx), "contingency_pct": float(params.contingency_pct),
                "logistics_pct": float(params.logistics_pct), "tax_pct": float(params.tax_pct)},
        warnings=warnings, unpriced_groups=unpriced,
    )


def determine_complexity(*, rooms: int, constraints: list[str], issue_severities: list[str], timeline_weeks: float | None,
                         estimated_weeks: float | None) -> tuple[str, list[str]]:
    """Deterministic complexity classification with human-readable reasons."""
    score, reasons = 0, []
    structural = ("remove wall", "knock", "structural", "load-bearing", "shift plumbing", "relocate", "extension")
    if any(any(k in c.lower() for k in structural) for c in constraints):
        score += 2
        reasons.append("Structural or services relocation requested")
    if "high" in issue_severities:
        score += 2
        reasons.append("High-severity visible issues (damp, cracks or similar)")
    elif "medium" in issue_severities:
        score += 1
        reasons.append("Medium-severity visible issues")
    if rooms >= 3:
        score += 1
        reasons.append("Three or more rooms in scope")
    rush = bool(timeline_weeks and estimated_weeks and timeline_weeks < estimated_weeks * 0.8)
    if rush:
        reasons.append("Requested timeline is shorter than the estimated programme")
    if rush and score >= 2:
        return "rush", reasons
    if rush or score >= 3:
        return "high", reasons
    if score == 0 and not reasons:
        return "standard", ["No complexity drivers detected"]
    return ("high" if score >= 3 else "standard"), reasons
