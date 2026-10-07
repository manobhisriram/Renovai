"""Request-id, access logging, metrics and security-header middleware."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability import metrics
from app.observability.context import new_request_id, request_id_var, user_id_var

log = logging.getLogger("renovai.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cache-Control": "no-store",
}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or new_request_id()
        token = request_id_var.set(rid[:64])
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid[:64]
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            metrics.HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            metrics.HTTP_LATENCY.labels(request.method, route).observe(elapsed)
            if route not in ("/health", "/ready", "/metrics"):
                uid = getattr(request.state, "user_id", None)
                if uid:
                    user_id_var.set(uid)
                log.info("%s %s -> %s", request.method, route, status, extra={"status": status, "ms": int(elapsed * 1000)})
            request_id_var.reset(token)
