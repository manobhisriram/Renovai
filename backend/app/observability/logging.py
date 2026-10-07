"""Structured JSON logging with secret + PII redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from app.observability.context import node_var, project_id_var, request_id_var, run_id_var, user_id_var

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(\"?\s*[:=]\s*\"?)((?:bearer\s+)?[^\s\",}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})"), r"\1***@\2"),
    (re.compile(r"(?<!\d)(\+?\d[\d\s\-]{8,}\d)(?!\d)"), "[PHONE]"),
]


def redact(text: str, secrets: list[str] | None = None) -> str:
    for secret in secrets or []:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = secrets or []

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage(), self.secrets)
            record.args = ()
        except Exception:  # noqa: S110  (a logging filter must never raise or log recursively)
            pass
        return True


class JsonFormatter(logging.Formatter):
    _SKIP = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "project_id": project_id_var.get(),
            "user_id": user_id_var.get(),
            "run_id": run_id_var.get(),
            "node": node_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in self._SKIP and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", secrets: list[str] | None = None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter(secrets))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
