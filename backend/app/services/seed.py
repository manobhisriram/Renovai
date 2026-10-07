"""Seeding: pricing catalog, regions, labour rates, sample leads, knowledge base and the admin user.

Everything seeded here is SAMPLE data (``is_sample=True``) and is labelled as such in the UI.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import Settings
from app.database.models import LaborRate, Lead, Material, Region, User
from app.pricing.seed_data import LABOR_RATES, REGIONS, material_rows
from app.rag.ingest import ingest_bytes
from app.rag.store import VectorStore

log = logging.getLogger(__name__)
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"


def seed_pricing(session: Session, currency: str) -> dict[str, int]:
    counts = {"materials": 0, "labor_rates": 0, "regions": 0}
    for row in material_rows(currency):
        if session.get(Material, row["sku"]) is None:
            session.add(Material(sku=row["sku"], group=row["group"], name=row["name"], tier=row["tier"], unit=row["unit"],
                                 unit_price=row["unit_price"], currency=row["currency"], labor_trade=row["labor_trade"],
                                 labor_hours_per_unit=row["labor_hours_per_unit"], lead_days=row["lead_days"],
                                 available=True, is_sample=True))
            counts["materials"] += 1
    for trade, rate in LABOR_RATES.items():
        if session.get(LaborRate, trade) is None:
            session.add(LaborRate(trade=trade, hourly_rate=rate, currency=currency, is_sample=True))
            counts["labor_rates"] += 1
    for key, name, mult, aliases in REGIONS:
        if session.get(Region, key) is None:
            session.add(Region(key=key, display_name=name, multiplier=mult, aliases=aliases, is_sample=True))
            counts["regions"] += 1
    session.commit()
    return counts


def seed_leads(session: Session) -> int:
    samples = [
        ("Priya Nair", "priya.nair@example.com", "+919000000001", {"style": "warm minimalist", "materials": ["oak veneer", "quartz"], "avoid": ["high-gloss finishes"]}),
        ("Rahul Menon", "rahul.menon@example.com", "+919000000002", {}),
        ("Aisha Khan", "aisha.khan@example.com", "+919000000003", {}),
    ]
    n = 0
    for name, email, phone, prefs in samples:
        if session.scalars(select(Lead).where(Lead.email == email)).first() is None:
            session.add(Lead(name=name, email=email, phone=phone, source="sample", preferences=prefs, is_sample=True))
            n += 1
    session.commit()
    return n


def seed_admin(session: Session, settings: Settings) -> bool:
    if settings.seed_admin_password is None:
        return False
    email = settings.seed_admin_email.lower()
    if session.scalars(select(User).where(User.email == email)).first():
        return False
    session.add(User(email=email, full_name="Administrator", password_hash=hash_password(settings.seed_admin_password.get_secret_value()), role="admin"))
    session.commit()
    return True


def seed_knowledge(session: Session, store: VectorStore, settings: Settings) -> int:
    store.ensure_collection()
    n = 0
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        ingest_bytes(session=session, store=store, settings=settings, filename=path.name, data=path.read_bytes(), is_sample=True)
        n += 1
    return n
