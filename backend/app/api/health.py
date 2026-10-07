from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.auth.deps import get_container
from app.observability.metrics import REGISTRY
from app.services.container import Container
from app.utils.errors import ForbiddenError

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
def ready(c: Container = Depends(get_container)) -> JSONResponse:
    """Readiness: dependencies this instance needs are reachable. 503 when a critical one is down."""
    checks: dict[str, dict] = {}

    def check(name: str, fn, critical: bool = True) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, type(exc).__name__
        checks[name] = {"ok": bool(ok), "critical": critical, "detail": detail}

    def _db():
        with c.session_factory() as s:
            s.execute(text("SELECT 1"))
        return True, "reachable"

    check("database", _db)
    check("vector_db", lambda: (c.store.healthy(), "qdrant"))
    check("storage", lambda: (c.storage.healthy(), c.settings.storage_backend))
    problems = c.settings.missing_required()
    check("configuration", lambda: (not problems, "; ".join(problems) or "ok"), critical=c.settings.is_production)
    check("llm_credentials", lambda: (c.provider.name == "mock" or not any("API_KEY" in p for p in problems),
                                      "mock provider" if c.provider.name == "mock" else c.provider.name), critical=False)
    if c.redis is not None:
        check("redis", lambda: (bool(c.redis.ping()), "reachable"), critical=False)
    ok = all(v["ok"] for v in checks.values() if v["critical"])
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request, c: Container = Depends(get_container)) -> Response:
    if not c.settings.metrics_enabled:
        return Response(status_code=404)
    token = c.settings.metrics_token
    if token is not None and not hmac.compare_digest(request.headers.get("x-metrics-token", ""), token.get_secret_value()):
        raise ForbiddenError("Metrics token required.")
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
