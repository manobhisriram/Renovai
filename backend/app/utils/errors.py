"""Application error types mapped to structured HTTP responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ExternalServiceError(AppError):
    """An external dependency (LLM, vector DB, CRM, storage) failed."""

    status_code = 502
    code = "external_service_error"


class ServiceNotConfigured(AppError):
    status_code = 503
    code = "service_not_configured"


class LLMUnavailable(ExternalServiceError):
    code = "llm_unavailable"


class LLMRequestError(ExternalServiceError):
    code = "llm_request_error"


class LLMOutputError(ExternalServiceError):
    code = "llm_output_invalid"


class ToolError(AppError):
    status_code = 500
    code = "tool_error"
