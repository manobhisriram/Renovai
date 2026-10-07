"""Deterministic budget fitter used by the negotiation flow.

Given a target budget it downgrades tiers (cheapest quality loss first), then drops optional lines, and
reports every step so the trade-offs can be explained. The LLM never changes a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.categories.registry import get_profile
from app.pricing.catalog import TIERS, Catalog
from app.pricing.engine import PricingParams, PricingResult, ScopeInput, price_scope


@dataclass
class FitStep:
    action: str  # downgrade | drop_optional
    group: str
    from_tier: str | None
    to_tier: str | None
    saving: Decimal


@dataclass
class FitResult:
    achievable: bool
    pricing: PricingResult
    tier_map: dict[str, str]
    dropped_groups: list[str]
    steps: list[FitStep] = field(default_factory=list)
    shortfall: Decimal = Decimal("0")

    def steps_dict(self) -> list[dict]:
        return [{"action": s.action, "group": s.group, "from_tier": s.from_tier, "to_tier": s.to_tier,
                 "saving": float(s.saving)} for s in self.steps]


def fit_to_budget(
    scope: list[ScopeInput], catalog: Catalog, params: PricingParams, budget: Decimal, *, category: str,
    start_tier: str = "standard", protected: set[str] | None = None, max_steps: int = 200,
) -> FitResult:
    profile = get_profile(category)
    protected = protected or set()
    tier_map = {s.group: start_tier for s in scope}
    dropped: set[str] = set()
    steps: list[FitStep] = []

    def weight(group: str) -> float:
        spec = profile.spec(group)
        base = spec.importance if spec else 1.0
        return base * (3.0 if group in protected else 1.0)

    def total_for(tmap: dict[str, str], drop: set[str]) -> PricingResult:
        return price_scope(scope, catalog, params, start_tier, tmap, exclude_groups=drop, label="fitted")

    current = total_for(tier_map, dropped)
    for _ in range(max_steps):
        if current.total <= budget:
            return FitResult(True, current, dict(current.tier_map), sorted(dropped), steps)
        best: tuple[float, str, str, PricingResult] | None = None
        for item in scope:
            g = item.group
            if g in dropped:
                continue
            tier = current.tier_map.get(g, tier_map[g])
            idx = TIERS.index(tier) if tier in TIERS else 1
            if idx == 0:
                continue
            new_tier = TIERS[idx - 1]
            if catalog.item(g, new_tier) is None:
                continue
            trial_map = {**tier_map, g: new_tier}
            trial = total_for(trial_map, dropped)
            saving = current.total - trial.total
            if saving <= 0:
                continue
            score = float(saving) / weight(g)
            if best is None or score > best[0]:
                best = (score, g, new_tier, trial)
        if best is not None:
            _, g, new_tier, trial = best
            steps.append(FitStep("downgrade", g, tier_map[g], new_tier, current.total - trial.total))
            tier_map[g] = new_tier
            current = trial
            continue
        # No downgrades left: drop the most expensive optional, unprotected line.
        droppable = [s for s in scope if s.optional and s.group not in dropped and s.group not in protected]
        best_drop: tuple[Decimal, str, PricingResult] | None = None
        for item in droppable:
            trial = total_for(tier_map, dropped | {item.group})
            saving = current.total - trial.total
            if saving > 0 and (best_drop is None or saving > best_drop[0]):
                best_drop = (saving, item.group, trial)
        if best_drop is None:
            break
        saving, g, trial = best_drop
        steps.append(FitStep("drop_optional", g, tier_map.get(g), None, saving))
        dropped.add(g)
        current = trial

    ok = current.total <= budget
    return FitResult(ok, current, dict(current.tier_map), sorted(dropped), steps,
                     shortfall=max(Decimal("0"), current.total - budget))
