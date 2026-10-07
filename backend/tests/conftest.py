from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.database import (
    Base,
    make_engine,
    models,  # noqa: F401
)
from app.graph.runtime import WorkflowService
from app.services import seed
from app.services.container import Container, build_container


def make_settings(tmp_path: Path, **over) -> Settings:
    base: dict = dict(  # noqa: C408
        app_env="test", database_url=f"sqlite:///{tmp_path}/test.db", llm_provider="mock", upload_dir=str(tmp_path / "uploads"),
        secret_key="test-secret-key-test-secret-key-0123456789", seed_admin_password="Adm1n-test-pass", cors_origins="http://localhost:5173",
        embedding_provider="hash", crm_provider="internal", approval_require_always=True, log_level="WARNING",
    )
    base.update(over)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def container(settings: Settings) -> Container:
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    c = build_container(settings, engine=engine, qdrant_in_memory=True)
    with c.session_factory() as s:
        seed.seed_pricing(s, settings.default_currency)
        seed.seed_leads(s)
        seed.seed_admin(s, settings)
        seed.seed_knowledge(s, c.store, settings)
    c._workflow = WorkflowService(c, checkpointer=__import__("langgraph.checkpoint.memory", fromlist=["MemorySaver"]).MemorySaver())
    return c


def jpeg_bytes(color=(180, 160, 140), size=(800, 600)) -> bytes:
    img = Image.new("RGB", size, color)
    for x in range(0, size[0], 40):  # add structure so sharpness/contrast are not degenerate
        for y in range(0, size[1], 40):
            if (x // 40 + y // 40) % 2:
                img.paste((color[0] - 40, color[1] - 40, color[2] - 40), (x, y, x + 40, y + 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def sample_jpeg() -> bytes:
    return jpeg_bytes()


@pytest.fixture
def client(container: Container):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(container=container)
    with TestClient(app) as c:
        yield c


def login(client, email="admin@renovai.local", password="Adm1n-test-pass") -> dict:  # noqa: S107
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client) -> dict:
    return login(client)
