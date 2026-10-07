"""Project-category registry.

A category is data, not code: adding a new vertical (e.g. 'commercial_fitout') means registering one
``CategoryProfile`` here (and seeding its materials). The LangGraph builder creates one planner node
per registered profile, so no graph rewrite is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SQM_TO_SQFT = 10.7639
Basis = Literal["floor_sqft", "wall_sqft", "count"]

PHASE_ORDER = ["demolition", "services", "carpentry", "surfaces", "painting", "fittings"]


@dataclass(frozen=True)
class GroupSpec:
    group: str
    unit: str
    basis: Basis
    factor: float  # floor/wall: multiplier of floor area (sqft); count: fixed default count
    per_sqm: float = 0.0  # extra count per sqm for count basis
    phase: str = "surfaces"
    optional: bool = False
    importance: float = 1.0  # higher = protect from downgrades when fitting to budget

    def default_quantity(self, area_sqm: float | None) -> float | None:
        if self.basis == "count":
            base = self.factor + (self.per_sqm * area_sqm if area_sqm else 0.0)
            return max(1.0, round(base))
        if area_sqm is None:
            return None
        return round(area_sqm * SQM_TO_SQFT * self.factor, 1)

    def sane_range(self, area_sqm: float | None) -> tuple[float, float] | None:
        default = self.default_quantity(area_sqm)
        if default is None:
            return None
        return (default * 0.15, default * 3.5)


@dataclass(frozen=True)
class CategoryProfile:
    key: str
    label: str
    description: str
    keywords: tuple[str, ...]
    groups: tuple[GroupSpec, ...]
    critical_fields: tuple[str, ...] = ("area_sqm",)
    recommended_fields: tuple[str, ...] = ("location", "budget", "timeline_weeks", "desired_style")
    crew_size: int = 4
    risk_notes: tuple[str, ...] = ()

    def spec(self, group: str) -> GroupSpec | None:
        return next((g for g in self.groups if g.group == group), None)

    @property
    def group_keys(self) -> list[str]:
        return [g.group for g in self.groups]


def _g(group: str, unit: str, basis: Basis, factor: float, phase: str, **kw: float | bool) -> GroupSpec:
    return GroupSpec(group=group, unit=unit, basis=basis, factor=factor, phase=phase, **kw)  # type: ignore[arg-type]


PROFILES: dict[str, CategoryProfile] = {}


def register(profile: CategoryProfile) -> CategoryProfile:
    PROFILES[profile.key] = profile
    return profile


register(CategoryProfile(
    key="kitchen_renovation", label="Kitchen renovation",
    description="Modular kitchens, countertops, backsplash, plumbing and electrical rework for kitchens.",
    keywords=("kitchen", "modular kitchen", "countertop", "chimney", "cabinet", "pantry"),
    crew_size=4,
    risk_notes=("Concealed plumbing/electrical condition is unknown until demolition.",),
    groups=(
        _g("demolition", "sqft", "floor_sqft", 1.0, "demolition", importance=0.5),
        _g("kitchen_cabinets", "sqft", "floor_sqft", 2.2, "carpentry", importance=3),
        _g("countertop", "sqft", "floor_sqft", 0.55, "surfaces", importance=2),
        _g("backsplash", "sqft", "floor_sqft", 0.8, "surfaces", optional=True),
        _g("floor_tiles", "sqft", "floor_sqft", 1.0, "surfaces", importance=1.5),
        _g("wall_paint", "sqft", "wall_sqft", 2.4, "painting", importance=0.5),
        _g("plumbing_fixtures", "nos", "count", 1, "fittings", importance=1.5),
        _g("electrical_points", "nos", "count", 6, "services", per_sqm=0.3, importance=1.5),
        _g("light_fixtures", "nos", "count", 4, "fittings", per_sqm=0.2, optional=True),
    ),
))

register(CategoryProfile(
    key="bathroom_renovation", label="Bathroom renovation",
    description="Waterproofing, tiling, sanitaryware, fittings and plumbing for bathrooms.",
    keywords=("bathroom", "toilet", "washroom", "shower", "sanitary", "vanity", "waterproof"),
    crew_size=3,
    risk_notes=("Waterproofing failures are costly; a membrane flood-test is assumed before tiling.",),
    groups=(
        _g("demolition", "sqft", "floor_sqft", 3.0, "demolition", importance=0.5),
        _g("waterproofing", "sqft", "floor_sqft", 1.4, "services", importance=3),
        _g("plumbing_works", "nos", "count", 5, "services", per_sqm=0.5, importance=2),
        _g("floor_tiles", "sqft", "floor_sqft", 1.0, "surfaces", importance=1.5),
        _g("wall_tiles", "sqft", "floor_sqft", 3.2, "surfaces", importance=1.5),
        _g("sanitaryware", "nos", "count", 1, "fittings", importance=2),
        _g("cp_fittings", "nos", "count", 1, "fittings", importance=1.5),
        _g("vanity", "nos", "count", 1, "carpentry", optional=True),
        _g("light_fixtures", "nos", "count", 2, "fittings", optional=True),
    ),
))

register(CategoryProfile(
    key="living_bedroom_renovation", label="Living / bedroom renovation",
    description="Ceilings, wardrobes, TV units, lighting, paint and flooring for living spaces and bedrooms.",
    keywords=("living room", "bedroom", "hall", "wardrobe", "tv unit", "false ceiling", "master bedroom", "drawing room"),
    crew_size=5,
    groups=(
        _g("wall_paint", "sqft", "wall_sqft", 2.6, "painting", importance=1),
        _g("false_ceiling", "sqft", "floor_sqft", 0.9, "carpentry", importance=1.5),
        _g("wood_flooring", "sqft", "floor_sqft", 1.0, "surfaces", importance=1.5),
        _g("wardrobe", "sqft", "floor_sqft", 0.5, "carpentry", importance=2),
        _g("tv_unit", "nos", "count", 1, "carpentry", optional=True),
        _g("electrical_points", "nos", "count", 4, "services", per_sqm=0.3, importance=1),
        _g("light_fixtures", "nos", "count", 4, "fittings", per_sqm=0.25, importance=1),
    ),
))

register(CategoryProfile(
    key="flooring_wall_renovation", label="Flooring & wall renovation",
    description="Replacing floors, wall finishes, panels and skirting.",
    keywords=("flooring", "floor", "tiles", "tiling", "wallpaper", "wall panel", "paint", "skirting", "repaint"),
    crew_size=4,
    groups=(
        _g("demolition", "sqft", "floor_sqft", 0.6, "demolition", importance=0.5),
        _g("floor_tiles", "sqft", "floor_sqft", 1.0, "surfaces", importance=2),
        _g("wood_flooring", "sqft", "floor_sqft", 1.0, "surfaces", optional=True, importance=2),
        _g("wall_panels", "sqft", "wall_sqft", 0.8, "carpentry", optional=True),
        _g("skirting", "rft", "floor_sqft", 0.6, "carpentry"),
        _g("wall_paint", "sqft", "wall_sqft", 2.6, "painting", importance=1),
    ),
))

register(CategoryProfile(
    key="outdoor_landscaping", label="Outdoor & landscaping",
    description="Gardens, balconies, terraces, paving, pergolas and outdoor lighting.",
    keywords=("garden", "landscap", "terrace", "balcony", "patio", "lawn", "pergola", "outdoor", "backyard"),
    crew_size=4,
    risk_notes=("Weather and soil conditions can change scope and timeline.",),
    groups=(
        _g("paving", "sqft", "floor_sqft", 0.5, "surfaces", importance=2),
        _g("turf_landscaping", "sqft", "floor_sqft", 0.5, "surfaces", importance=2),
        _g("pergola", "sqft", "floor_sqft", 0.2, "carpentry", optional=True),
        _g("planters", "nos", "count", 4, "fittings", per_sqm=0.1, optional=True),
        _g("outdoor_lighting", "nos", "count", 4, "fittings", per_sqm=0.15, optional=True),
    ),
))

register(CategoryProfile(
    key="smart_home_upgrade", label="Smart-home upgrade",
    description="Smart switches, locks, cameras, lighting and hubs retrofitted into existing homes.",
    keywords=("smart home", "smart", "automation", "alexa", "google home", "smart lock", "cctv", "camera", "home automation"),
    crew_size=2, recommended_fields=("location", "budget", "timeline_weeks"),
    groups=(
        _g("smart_hub", "nos", "count", 1, "fittings", importance=3),
        _g("smart_switches", "nos", "count", 8, "services", per_sqm=0.15, importance=2),
        _g("smart_lighting", "nos", "count", 6, "fittings", per_sqm=0.1, optional=True),
        _g("smart_lock", "nos", "count", 1, "fittings", optional=True),
        _g("smart_cameras", "nos", "count", 3, "fittings", optional=True),
    ),
))

register(CategoryProfile(
    key="general_interior_renovation", label="General interior renovation",
    description="Whole-home or multi-room interior refresh not covered by a more specific category.",
    keywords=("interior", "renovation", "redesign", "makeover", "2bhk", "3bhk", "1bhk", "flat", "apartment", "home"),
    crew_size=6,
    groups=(
        _g("demolition", "sqft", "floor_sqft", 0.5, "demolition", importance=0.5),
        _g("electrical_points", "nos", "count", 10, "services", per_sqm=0.35, importance=1),
        _g("false_ceiling", "sqft", "floor_sqft", 0.6, "carpentry", optional=True, importance=1.5),
        _g("wardrobe", "sqft", "floor_sqft", 0.3, "carpentry", importance=2),
        _g("floor_tiles", "sqft", "floor_sqft", 1.0, "surfaces", importance=1.5),
        _g("wall_paint", "sqft", "wall_sqft", 2.8, "painting", importance=1),
        _g("light_fixtures", "nos", "count", 8, "fittings", per_sqm=0.3, importance=1),
        _g("tv_unit", "nos", "count", 1, "carpentry", optional=True),
    ),
))

DEFAULT_CATEGORY = "general_interior_renovation"


def get_profile(key: str | None) -> CategoryProfile:
    return PROFILES.get(key or "", PROFILES[DEFAULT_CATEGORY])


def keyword_classify(text: str) -> tuple[str, float]:
    """Cheap deterministic classifier used as a fallback and as a cross-check against the LLM."""
    low = text.lower()
    best, best_score = DEFAULT_CATEGORY, 0
    for key, prof in PROFILES.items():
        if key == DEFAULT_CATEGORY:
            continue
        score = sum(2 if " " in kw else 1 for kw in prof.keywords if kw in low)
        if score > best_score:
            best, best_score = key, score
    return best, min(1.0, 0.35 + 0.15 * best_score) if best_score else 0.3


def all_group_keys() -> set[str]:
    return {g.group for p in PROFILES.values() for g in p.groups}


def phase_of(group: str) -> str:
    for prof in PROFILES.values():
        spec = prof.spec(group)
        if spec:
            return spec.phase
    return "surfaces"


# Typical floor areas (sqm) used ONLY when the client never supplies one; always surfaced as an assumption.
TYPICAL_AREA_SQM: dict[str, float] = {
    "kitchen_renovation": 10.0, "bathroom_renovation": 4.5, "living_bedroom_renovation": 18.0,
    "flooring_wall_renovation": 40.0, "outdoor_landscaping": 25.0, "smart_home_upgrade": 80.0,
    "general_interior_renovation": 70.0,
}
