"""Request-scoped context propagated through logs and telemetry."""

from __future__ import annotations

import contextvars
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
project_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("project_id", default="-")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
node_var: contextvars.ContextVar[str] = contextvars.ContextVar("node", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
