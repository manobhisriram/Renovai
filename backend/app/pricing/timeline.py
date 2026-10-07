"""Deterministic programme estimate from labour hours and material lead times."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from app.categories.registry import PHASE_ORDER, get_profile, phase_of
from app.pricing.engine import PricedLine

HOURS_PER_DAY = 8
WORKING_DAYS_PER_WEEK = 6
CURING_BUFFER = Decimal("0.10")


@dataclass
class TimelineEstimate:
    phases: list[dict]
    working_days: int
    lead_time_delay_days: int
    weeks: float
    critical_material: str | None

    def to_dict(self) -> dict:
        return {"phases": self.phases, "working_days": self.working_days,
                "lead_time_delay_days": self.lead_time_delay_days, "weeks": self.weeks,
                "critical_material": self.critical_material}


def estimate_timeline(lines: list[PricedLine], category: str, *, crew_size: int | None = None) -> TimelineEstimate:
    crew = crew_size or get_profile(category).crew_size
    hours_by_phase: dict[str, Decimal] = {p: Decimal("0") for p in PHASE_ORDER}
    for ln in lines:
        hours_by_phase[phase_of(ln.group)] = hours_by_phase.get(phase_of(ln.group), Decimal("0")) + ln.labor_hours

    phases, cursor = [], 0
    start_by_phase: dict[str, int] = {}
    for phase in PHASE_ORDER:
        hours = hours_by_phase.get(phase, Decimal("0"))
        days = 0 if hours <= 0 else max(1, math.ceil(float(hours) / (crew * HOURS_PER_DAY)))
        start_by_phase[phase] = cursor
        if days:
            phases.append({"phase": phase, "start_day": cursor, "days": days, "labor_hours": float(hours)})
        cursor += days

    # Materials can be ordered on day 0; delay only if they arrive after their phase would start.
    delay, critical = 0, None
    for ln in lines:
        start = start_by_phase.get(phase_of(ln.group), 0)
        wait = ln.lead_days - start
        if wait > delay:
            delay, critical = wait, ln.name
    working_days = cursor + delay
    working_days = math.ceil(working_days * float(1 + CURING_BUFFER)) if working_days else 0
    weeks = round(working_days / WORKING_DAYS_PER_WEEK, 1)
    return TimelineEstimate(phases=phases, working_days=working_days, lead_time_delay_days=max(0, delay),
                            weeks=weeks, critical_material=critical)
