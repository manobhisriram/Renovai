"""Controlled tool execution.

The LLM never executes code. It can only *request* a tool by name with JSON arguments; the registry
validates the arguments, enforces the caller/allow-list, applies a timeout, logs and counts the call, and
returns a structured result. Side-effecting tools are application-only (``llm_exposed=False``).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.llm.schema_utils import tool_schema
from app.llm.types import ToolSpec
from app.observability import metrics
from app.utils.errors import ForbiddenError

log = logging.getLogger(__name__)
Caller = Literal["llm", "app"]
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")


@dataclass
class ToolContext:
    """Dependencies handed to tool handlers. Handlers must not reach for globals."""

    deps: Any  # app.services.container.Container
    project_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDef:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], BaseModel | dict[str, Any]]
    llm_exposed: bool = True
    side_effect: bool = False
    timeout_s: float | None = None


@dataclass
class ToolResult:
    ok: bool
    output: dict[str, Any] | None
    error: str | None
    latency_ms: int

    def as_text(self) -> str:
        return json.dumps(self.output if self.ok else {"error": self.error}, default=str)


class ToolRegistry:
    def __init__(self, default_timeout_s: float = 15.0):
        self._tools: dict[str, ToolDef] = {}
        self._default_timeout = default_timeout_s

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def names(self, *, llm_only: bool = False) -> list[str]:
        return [n for n, t in self._tools.items() if t.llm_exposed or not llm_only]

    def specs(self, allowed: list[str]) -> list[ToolSpec]:
        out = []
        for name in allowed:
            tool = self._tools[name]
            if not tool.llm_exposed:
                raise ForbiddenError(f"tool '{name}' is not available to the model")
            out.append(ToolSpec(name=tool.name, description=tool.description, input_schema=tool_schema(tool.input_model)))
        return out

    def execute(self, name: str, raw_input: dict[str, Any], ctx: ToolContext, *, caller: Caller,
                allowed: set[str] | None = None) -> ToolResult:
        start = time.perf_counter()

        def done(ok: bool, output: dict[str, Any] | None, error: str | None) -> ToolResult:
            ms = int((time.perf_counter() - start) * 1000)
            metrics.TOOL_CALLS.labels(name, "ok" if ok else "error").inc()
            log.info("tool %s %s", name, "ok" if ok else f"failed: {error}", extra={"tool": name, "ms": ms, "caller": caller})
            return ToolResult(ok, output, error, ms)

        tool = self._tools.get(name)
        if tool is None:
            return done(False, None, f"unknown tool '{name}'")
        if caller == "llm":
            if not tool.llm_exposed:
                return done(False, None, f"tool '{name}' is not permitted for model use")
            if allowed is not None and name not in allowed:
                return done(False, None, f"tool '{name}' is not allowed in this step")
        try:
            args = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            return done(False, None, "invalid arguments: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4]))
        timeout = tool.timeout_s or self._default_timeout
        future = _POOL.submit(tool.handler, ctx, args)
        try:
            result = future.result(timeout=timeout)
        except FuturesTimeout:
            future.cancel()
            return done(False, None, f"timed out after {timeout:.0f}s")
        except Exception as exc:
            log.warning("tool %s raised %s", name, type(exc).__name__)
            return done(False, None, f"{type(exc).__name__}: {str(exc)[:200]}")
        output = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        return done(True, output, None)
