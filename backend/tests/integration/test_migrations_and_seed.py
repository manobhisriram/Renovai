from __future__ import annotations

from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.database import (
    Base,
    make_engine,
    models,  # noqa: F401
)


def test_alembic_upgrade_creates_every_model_table_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path}/mig.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    tables = set(inspect(make_engine(url)).get_table_names())
    assert set(Base.metadata.tables) <= tables
    command.downgrade(cfg, "base")
    assert set(Base.metadata.tables).isdisjoint(set(inspect(make_engine(url)).get_table_names()))


def test_models_match_migration_no_drift(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite:///{tmp_path}/drift.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    with make_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models changed without a migration: {diff}"


def test_seed_is_idempotent_and_labelled_sample(container, settings):
    from sqlalchemy import func, select

    from app.database.models import Lead, Material
    from app.services import seed

    with container.session_factory() as s:
        n = s.scalar(select(func.count(Material.sku)))
        assert n == 31 * 3
        again = seed.seed_pricing(s, "INR")
        assert again == {"materials": 0, "labor_rates": 0, "regions": 0}
        assert all(m.is_sample for m in s.scalars(select(Material)))
        assert all(lead.is_sample for lead in s.scalars(select(Lead)))
