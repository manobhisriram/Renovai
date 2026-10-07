from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agents.planning import default_scope, validate_scope
from app.agents.quoting import grounded_amounts
from app.agents.requirements import normalise_requirements, recompute_missing
from app.categories.registry import PROFILES, get_profile, keyword_classify
from app.graph.nodes import match_groups
from app.pricing.catalog import Catalog, MaterialItem
from app.pricing.seed_data import material_rows
from app.schemas.ai import DimensionEstimate, QuoteNarrative, Requirements, RoomVisionAnalysis, ScopeLine, ScopePlan
from app.vision.analyzer import sanitize_vision
from app.vision.cv import CVResult


def cv(flags=()):
    return CVResult(800, 600, 120, 50, 100, [], "neutral", list(flags))


def test_vision_honesty_clamps():
    v = RoomVisionAnalysis(dimensions=DimensionEstimate(width_m=4, length_m=3, area_sqm=12, provenance="detected", confidence=0.99), overall_confidence=0.99)
    out = sanitize_vision(v, cv(["possibly_blurry"]))
    assert out.dimensions.provenance == "estimated" and out.dimensions.confidence <= 0.6
    assert out.overall_confidence <= 0.5
    assert any("not measurements" in x for x in out.limitations) and any("blurry" in x for x in out.limitations)
    empty = sanitize_vision(RoomVisionAnalysis(), cv())
    assert empty.dimensions.provenance == "unknown"


def test_schemas_reject_out_of_range_values():
    with pytest.raises(ValidationError):
        Requirements(timeline_weeks=-1)
    with pytest.raises(ValidationError):
        Requirements(confidence=1.5)
    with pytest.raises(ValidationError):
        ScopeLine(group="x", quantity=0, unit="sqft")
    with pytest.raises(ValidationError):
        DimensionEstimate(area_sqm=-3)
    with pytest.raises(ValidationError):
        ScopePlan(lines=[])


def test_requirements_normalisation_uses_known_facts_and_recomputes_missing():
    req = Requirements(desired_style="modern", confidence=0.7, missing_information=["colour"])
    out = normalise_requirements(req, known={"area_sqm": 11.0, "location": "Chennai"}, category="kitchen_renovation")
    assert out["area_sqm"] == 11.0 and out["provenance"]["area_sqm"] == "user_provided"
    assert "area_sqm" not in out["missing_information"] and "budget" in out["missing_information"] and "colour" in out["missing_information"]
    # photo-derived area is only a hint, never counted as provided
    hint = normalise_requirements(Requirements(), known={}, category="kitchen_renovation", vision_area_hint=9.5)
    assert hint["vision_area_hint_sqm"] == 9.5 and "area_sqm" in hint["missing_information"]
    assert "area_sqm" in recompute_missing({"area_sqm": 12, "provenance": {"area_sqm": "estimated"}}, "kitchen_renovation")["missing_information"]


def test_keyword_classifier_and_registry_extensibility():
    assert keyword_classify("redo my kitchen with modular cabinets")[0] == "kitchen_renovation"
    assert keyword_classify("shower leaking, new tiles in the washroom")[0] == "bathroom_renovation"
    assert keyword_classify("garden and terrace pergola")[0] == "outdoor_landscaping"
    assert keyword_classify("install smart locks and cameras")[0] == "smart_home_upgrade"
    assert keyword_classify("blah")[0] == "general_interior_renovation"
    assert {"kitchen_renovation", "bathroom_renovation", "living_bedroom_renovation", "flooring_wall_renovation",
            "outdoor_landscaping", "smart_home_upgrade", "general_interior_renovation"} <= set(PROFILES)


def catalog():
    mats = [MaterialItem(sku=r["sku"], group=r["group"], name=r["name"], tier=r["tier"], unit=r["unit"], unit_price=Decimal(str(r["unit_price"])),
                         currency="INR", labor_trade=r["labor_trade"], labor_hours_per_unit=Decimal("0.1"), lead_days=3) for r in material_rows()]
    return Catalog(mats, {}, [])


def test_scope_validation_drops_unknown_merges_duplicates_flags_outliers():
    prof = get_profile("kitchen_renovation")
    plan = ScopePlan(lines=[
        ScopeLine(group="kitchen_cabinets", quantity=24, unit="sqft"),
        ScopeLine(group="kitchen_cabinets", quantity=30, unit="sqft"),
        ScopeLine(group="gold_plating", quantity=1, unit="nos"),
        ScopeLine(group="countertop", quantity=9000, unit="sqft"),
        ScopeLine(group="floor_tiles", quantity=120, unit="m"),
    ])
    lines, flags = validate_scope(plan, prof, catalog(), area_sqm=11.0)
    groups = {ln["group"]: ln for ln in lines}
    assert "gold_plating" not in groups and groups["kitchen_cabinets"]["quantity"] == 30
    assert groups["floor_tiles"]["unit"] == "sqft"
    codes = {f["code"] for f in flags}
    assert {"unknown_group", "duplicate_group", "quantity_outlier", "unit_mismatch"} <= codes


def test_default_scope_scales_with_area():
    prof = get_profile("kitchen_renovation")
    small, big = default_scope(prof, 8), default_scope(prof, 16)
    qty = lambda s, g: next(x["quantity"] for x in s if x["group"] == g)
    assert qty(big, "kitchen_cabinets") == pytest.approx(2 * qty(small, "kitchen_cabinets"), rel=0.01)


def test_narrative_grounding_flags_invented_prices():
    ok = QuoteNarrative(summary="Standard option is about INR 663,775 in total; contact us in 2025.", assumptions=["Area 11 sqm"])
    assert grounded_amounts(ok, [663775.02]) == []
    bad = QuoteNarrative(summary="We can do this for only INR 4,10,000 guaranteed", risks=["Could rise by 25,000"])
    stray = grounded_amounts(bad, [663775.02])
    assert 410000.0 in stray and 25000.0 in stray, stray


def test_group_matching_from_free_text():
    groups = ["false_ceiling", "backsplash", "wardrobe", "floor_tiles", "light_fixtures"]
    assert match_groups(["the backsplash", "false ceiling"], groups) == {"backsplash", "false_ceiling"}
    assert match_groups(["wardrobes"], groups) == {"wardrobe"}
    assert match_groups(["something unrelated"], groups) == set()
