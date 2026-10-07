"""In-memory snapshot of pricing data, loaded from the database."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import LaborRate, Material, Region

TIERS = ("budget", "standard", "premium")


@dataclass(frozen=True)
class MaterialItem:
    sku: str
    group: str
    name: str
    tier: str
    unit: str
    unit_price: Decimal
    currency: str
    labor_trade: str
    labor_hours_per_unit: Decimal
    lead_days: int
    available: bool = True
    is_sample: bool = False


@dataclass(frozen=True)
class RegionItem:
    key: str
    display_name: str
    multiplier: Decimal
    aliases: tuple[str, ...]


class Catalog:
    def __init__(self, materials: list[MaterialItem], labor_rates: dict[str, Decimal], regions: list[RegionItem]):
        self._by_group_tier: dict[tuple[str, str], MaterialItem] = {}
        for m in materials:
            if m.available:
                self._by_group_tier[(m.group, m.tier)] = m
        self.materials = materials
        self.labor_rates = labor_rates
        self.regions = {r.key: r for r in regions}

    @classmethod
    def from_session(cls, session: Session) -> Catalog:
        mats = [
            MaterialItem(
                sku=m.sku, group=m.group, name=m.name, tier=m.tier, unit=m.unit,
                unit_price=Decimal(str(m.unit_price)), currency=m.currency, labor_trade=m.labor_trade,
                labor_hours_per_unit=Decimal(str(m.labor_hours_per_unit)), lead_days=m.lead_days,
                available=m.available, is_sample=m.is_sample,
            )
            for m in session.scalars(select(Material))
        ]
        rates = {r.trade: Decimal(str(r.hourly_rate)) for r in session.scalars(select(LaborRate))}
        regions = [
            RegionItem(r.key, r.display_name, Decimal(str(r.multiplier)), tuple(a.lower() for a in (r.aliases or [])))
            for r in session.scalars(select(Region))
        ]
        return cls(mats, rates, regions)

    # --- lookups -----------------------------------------------------------
    def groups(self) -> set[str]:
        return {m.group for m in self.materials}

    def item(self, group: str, tier: str) -> MaterialItem | None:
        return self._by_group_tier.get((group, tier))

    def item_or_nearest(self, group: str, tier: str) -> MaterialItem | None:
        """Exact tier, else the closest available tier for that group."""
        if (found := self.item(group, tier)):
            return found
        order = list(TIERS)
        idx = order.index(tier) if tier in order else 1
        for delta in (1, -1, 2, -2):
            j = idx + delta
            if 0 <= j < len(order) and (alt := self.item(group, order[j])):
                return alt
        return None

    def labor_rate(self, trade: str) -> Decimal | None:
        return self.labor_rates.get(trade)

    def resolve_region(self, location: str | None) -> RegionItem | None:
        default = self.regions.get("default")
        if not location:
            return default
        low = location.lower()
        for region in self.regions.values():
            if region.key == "default":
                continue
            if any(alias in low for alias in region.aliases) or region.key in low:
                return region
        return default

    def is_empty(self) -> bool:
        return not self.materials
