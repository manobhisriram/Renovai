from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_db, rate_limit, require_roles
from app.categories.registry import PROFILES
from app.database.models import LaborRate, Material, Region
from app.schemas.api import MaterialUpdate
from app.services.audit import audit
from app.utils.errors import NotFoundError

router = APIRouter(tags=["pricing"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


def material_view(m: Material) -> dict:
    return {"sku": m.sku, "group": m.group, "name": m.name, "tier": m.tier, "unit": m.unit, "unit_price": float(m.unit_price),
            "currency": m.currency, "labor_trade": m.labor_trade, "labor_hours_per_unit": m.labor_hours_per_unit,
            "lead_days": m.lead_days, "available": m.available, "is_sample": m.is_sample}


@router.get("/materials")
def list_materials(group: str | None = None, tier: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Material).order_by(Material.group, Material.tier)
    if group:
        stmt = stmt.where(Material.group == group)
    if tier:
        stmt = stmt.where(Material.tier == tier)
    return [material_view(m) for m in db.scalars(stmt)]


@router.put("/materials/{sku}")
def update_material(sku: str, body: MaterialUpdate, db: Session = Depends(get_db), user=Depends(require_roles("admin"))) -> dict:
    m = db.get(Material, sku)
    if m is None:
        raise NotFoundError("Material not found.")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(m, k, v)
    if changes:
        m.is_sample = False  # an edited price is no longer sample data
    audit(db, user.email, "material.updated", detail={"sku": sku, **changes})
    db.commit()
    return material_view(m)


@router.get("/pricing/config")
def pricing_config(db: Session = Depends(get_db)) -> dict:
    return {
        "labor_rates": [{"trade": r.trade, "hourly_rate": float(r.hourly_rate), "currency": r.currency, "is_sample": r.is_sample} for r in db.scalars(select(LaborRate))],
        "regions": [{"key": r.key, "name": r.display_name, "multiplier": r.multiplier, "is_sample": r.is_sample} for r in db.scalars(select(Region))],
        "categories": [{"key": p.key, "label": p.label, "description": p.description, "groups": p.group_keys} for p in PROFILES.values()],
        "formula": "line = (qty x unit_price + qty x labour_hours x hourly_rate x complexity) x regional; total = (sub + contingency) x (1 + tax)",
    }
