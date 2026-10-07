from __future__ import annotations

from decimal import Decimal

import pytest

from app.pricing.catalog import Catalog, MaterialItem, RegionItem
from app.pricing.engine import PricingParams, ScopeInput, determine_complexity, make_params, price_scope
from app.pricing.fitter import fit_to_budget
from app.pricing.seed_data import material_rows
from app.pricing.timeline import estimate_timeline


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    mats = [MaterialItem(sku=r["sku"], group=r["group"], name=r["name"], tier=r["tier"], unit=r["unit"], unit_price=Decimal(str(r["unit_price"])),
                         currency="INR", labor_trade=r["labor_trade"], labor_hours_per_unit=Decimal(str(r["labor_hours_per_unit"])), lead_days=r["lead_days"])
            for r in material_rows()]
    rates = {"carpenter": Decimal("280"), "tiler": Decimal("260"), "painter": Decimal("220"), "electrician": Decimal("300"),
             "plumber": Decimal("300"), "civil": Decimal("240"), "stone_mason": Decimal("320")}
    regions = [RegionItem("default", "Default", Decimal("1.0"), ()), RegionItem("mumbai", "Mumbai", Decimal("1.22"), ("mumbai",))]
    return Catalog(mats, rates, regions)


PARAMS = PricingParams(contingency_pct=Decimal("8"), logistics_pct=Decimal("3"), tax_pct=Decimal("18"))


def test_known_value_hand_calculation(catalog):
    # 100 sqft of standard floor tiles: price 110, 0.18 labour hrs/unit at tiler 260/hr
    res = price_scope([ScopeInput("floor_tiles", Decimal("100"))], catalog, PARAMS, "standard")
    materials = Decimal("100") * Decimal("110")              # 11,000.00
    labor = Decimal("100") * Decimal("0.18") * Decimal("260")  # 4,680.00
    logistics = materials * Decimal("0.03")                  # 330.00
    subtotal = materials + labor + logistics                 # 16,010.00
    contingency = subtotal * Decimal("0.08")                 # 1,280.80
    tax = (subtotal + contingency) * Decimal("0.18")         # 3,112.4...
    expected = (subtotal + contingency) + tax.quantize(Decimal("0.01"))
    assert res.materials_subtotal == materials and res.labor_subtotal == labor and res.logistics == logistics
    assert res.subtotal == subtotal and res.contingency == contingency
    assert res.total == expected.quantize(Decimal("0.01"))


def test_components_always_reconcile_to_total(catalog):
    scope = [ScopeInput("kitchen_cabinets", Decimal("43.7")), ScopeInput("countertop", Decimal("12.3")), ScopeInput("light_fixtures", Decimal("7"))]
    for tier in ("budget", "standard", "premium"):
        r = price_scope(scope, catalog, PARAMS, tier)
        assert r.subtotal == r.materials_subtotal + r.labor_subtotal + r.logistics
        assert r.total == r.subtotal + r.contingency + r.tax
        assert sum((ln.line_total for ln in r.lines), Decimal("0")) == r.materials_subtotal + r.labor_subtotal
        assert all(x == x.quantize(Decimal("0.01")) for x in (r.total, r.tax, r.contingency))


def test_tiers_are_monotonic_and_quantity_scales(catalog):
    scope = [ScopeInput("kitchen_cabinets", Decimal("40")), ScopeInput("floor_tiles", Decimal("120"))]
    totals = [price_scope(scope, catalog, PARAMS, t).total for t in ("budget", "standard", "premium")]
    assert totals[0] < totals[1] < totals[2]
    double = [ScopeInput(s.group, s.quantity * 2) for s in scope]
    assert price_scope(double, catalog, PARAMS, "standard").total > price_scope(scope, catalog, PARAMS, "standard").total


def test_regional_multiplier_and_complexity_apply(catalog):
    scope = [ScopeInput("floor_tiles", Decimal("100"))]
    base = price_scope(scope, catalog, PARAMS, "standard").total
    mumbai = make_params(catalog, "Andheri, Mumbai", "standard", contingency_pct=8, logistics_pct=3, tax_pct=18, currency="INR")
    assert mumbai.region_key == "mumbai"
    assert price_scope(scope, catalog, mumbai, "standard").total > base * Decimal("1.2")
    hard = make_params(catalog, None, "high", contingency_pct=8, logistics_pct=3, tax_pct=18, currency="INR")
    assert price_scope(scope, catalog, hard, "standard").total > base  # labour is 20% dearer


def test_unknown_group_is_reported_not_priced(catalog):
    r = price_scope([ScopeInput("flying_carpet", Decimal("1")), ScopeInput("floor_tiles", Decimal("10"))], catalog, PARAMS)
    assert r.unpriced_groups == ["flying_carpet"] and any("flying_carpet" in w for w in r.warnings) and len(r.lines) == 1


def test_zero_and_negative_quantities_are_ignored(catalog):
    r = price_scope([ScopeInput("floor_tiles", Decimal("0")), ScopeInput("wall_paint", Decimal("-5"))], catalog, PARAMS)
    assert r.total == 0 and len(r.warnings) == 2


def test_fitter_meets_budget_with_documented_steps(catalog):
    scope = [ScopeInput("kitchen_cabinets", Decimal("45")), ScopeInput("countertop", Decimal("12")), ScopeInput("backsplash", Decimal("20"), optional=True),
             ScopeInput("floor_tiles", Decimal("120")), ScopeInput("light_fixtures", Decimal("6"), optional=True)]
    std = price_scope(scope, catalog, PARAMS, "standard").total
    target = std * Decimal("0.8")
    fit = fit_to_budget(scope, catalog, PARAMS, target, category="kitchen_renovation")
    assert fit.achievable and fit.pricing.total <= target
    assert fit.steps and all(s.saving > 0 for s in fit.steps)


def test_fitter_protects_priorities_and_reports_unachievable(catalog):
    scope = [ScopeInput("kitchen_cabinets", Decimal("45")), ScopeInput("floor_tiles", Decimal("100"))]
    std = price_scope(scope, catalog, PARAMS, "standard").total
    fit = fit_to_budget(scope, catalog, PARAMS, std * Decimal("0.8"), category="kitchen_renovation", protected={"kitchen_cabinets"})
    changed = [s.group for s in fit.steps]
    assert changed and changed[0] == "floor_tiles"  # protected cabinets are downgraded last
    impossible = fit_to_budget(scope, catalog, PARAMS, Decimal("1000"), category="kitchen_renovation")
    assert not impossible.achievable and impossible.shortfall > 0 and impossible.pricing.total > 0


def test_timeline_is_deterministic_and_lead_time_aware(catalog):
    r = price_scope([ScopeInput("kitchen_cabinets", Decimal("45")), ScopeInput("floor_tiles", Decimal("120"))], catalog, PARAMS, "standard")
    t1, t2 = estimate_timeline(r.lines, "kitchen_renovation"), estimate_timeline(r.lines, "kitchen_renovation")
    assert t1.to_dict() == t2.to_dict() and t1.weeks > 0 and t1.working_days > 0
    premium = price_scope([ScopeInput("kitchen_cabinets", Decimal("45"))], catalog, PARAMS, "premium")
    assert estimate_timeline(premium.lines, "kitchen_renovation").critical_material  # 42-day cabinet lead time dominates


def test_complexity_drivers():
    lvl, why = determine_complexity(rooms=1, constraints=[], issue_severities=[], timeline_weeks=None, estimated_weeks=6)
    assert lvl == "standard" and why
    lvl, _ = determine_complexity(rooms=4, constraints=["remove wall between kitchen and hall"], issue_severities=["high"], timeline_weeks=None, estimated_weeks=6)
    assert lvl == "high"
    lvl, why = determine_complexity(rooms=4, constraints=["remove wall"], issue_severities=[], timeline_weeks=3, estimated_weeks=8)
    assert lvl == "rush" and any("shorter" in w for w in why)
