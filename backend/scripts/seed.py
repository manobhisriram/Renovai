"""Seed sample data:  python -m scripts.seed [--reset-knowledge]

Run AFTER `alembic upgrade head`. Safe to re-run (idempotent).
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from app.config import get_settings
from app.database import make_engine, make_session_factory
from app.rag.embeddings import build_embedder
from app.rag.store import VectorStore, make_client
from app.services import seed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-knowledge", action="store_true", help="drop and rebuild the Qdrant collection first")
    ap.add_argument("--skip-knowledge", action="store_true", help="do not (re)ingest the sample documents")
    args = ap.parse_args()
    settings = get_settings()
    sf = make_session_factory(make_engine(settings.database_url))
    with sf() as s:
        print("pricing:", seed.seed_pricing(s, settings.default_currency))
        print("sample leads added:", seed.seed_leads(s))
        created = seed.seed_admin(s, settings)
        print("admin user:", f"created ({settings.seed_admin_email})" if created else "unchanged (set SEED_ADMIN_PASSWORD to create one)")
        if not args.skip_knowledge:
            store = VectorStore(make_client(settings), build_embedder(settings), settings.qdrant_collection)
            if args.reset_knowledge:
                with contextlib.suppress(Exception):  # collection may not exist yet
                    store.client.delete_collection(settings.qdrant_collection)
            print("knowledge documents ingested:", seed.seed_knowledge(s, store, settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
