"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.observability.context import request_id_var
from app.observability.logging import configure_logging
from app.observability.middleware import ObservabilityMiddleware
from app.services.container import Container, build_container
from app.utils.errors import AppError
from app.utils.ratelimit import RateLimiter

log = logging.getLogger("renovai")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, settings.secret_values())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_for_startup()  # production: refuse to start with unsafe/missing configuration
        for problem in settings.missing_required():
            log.warning("configuration: %s", problem)
        c = container or build_container(settings)
        app.state.container = c
        app.state.limiter = RateLimiter(c.redis)
        try:
            c.store.ensure_collection()
        except Exception as exc:  # the API still starts; /ready reports the vector DB as down
            log.warning("vector database not ready at startup: %s", type(exc).__name__)
        recovered = c.workflow.recover_stale_runs()
        if recovered:
            log.warning("marked %s stale workflow run(s) as failed", recovered)
        log.info("RenovAI started env=%s llm=%s crm=%s", settings.app_env, c.provider.name, c.crm.name)
        yield

    app = FastAPI(title=f"{settings.app_name} API", version=settings.app_version, lifespan=lifespan,
                  description="Agentic AI platform for interior design & renovation: intake, vision, RAG, deterministic pricing, "
                              "quotes, negotiation, approvals and CRM sync.",
                  docs_url="/docs" if not settings.is_production else None, redoc_url=None,
                  openapi_url="/openapi.json" if not settings.is_production else None)
    if container is not None:  # tests: available before lifespan runs
        app.state.container = container
        app.state.limiter = RateLimiter(container.redis)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID"], max_age=600)
    app.add_middleware(ObservabilityMiddleware)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request_id_var.get()}},
                            status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()[:10]]
        return JSONResponse({"error": {"code": "validation_failed", "message": "Some fields are invalid.", "details": {"fields": fields},
                                       "request_id": request_id_var.get()}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong on our side. Try again; if it persists, share the request ID with support.",
                                       "details": {}, "request_id": request_id_var.get()}}, status_code=500)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()
