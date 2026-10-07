"""High-level LLM client: routing, telemetry, structured output with validation-retry, and a tool loop."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.router import ModelRouter
from app.llm.safety import SYSTEM_GUARD, wrap_untrusted
from app.llm.schema_utils import tool_schema
from app.llm.types import AssistantTurn, LLMProvider, Message, ToolSpec
from app.observability.telemetry import LLMCallRecord, Telemetry, estimate_cost
from app.tools.registry import ToolContext, ToolRegistry
from app.utils.errors import ExternalServiceError, LLMOutputError, LLMRequestError, LLMUnavailable

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

MAX_VALIDATION_RETRIES = 1


def final_tool_name(schema: type[BaseModel]) -> str:
    return f"submit_{schema.__name__}"


class LLMClient:
    def __init__(self, settings: Settings, provider: LLMProvider, router: ModelRouter, telemetry: Telemetry,
                 tools: ToolRegistry | None = None):
        self.settings = settings
        self.provider = provider
        self.router = router
        self.telemetry = telemetry
        self.tools = tools

    # ------------------------------------------------------------------ low level
    def _turn(self, task: str, system: str, messages: list[Message], tool_specs: list[ToolSpec], tool_choice: str) -> AssistantTurn:
        """One provider call with model fallback + telemetry."""
        last_exc: Exception | None = None
        for tier, model in self.router.candidates(task):
            start = time.perf_counter()
            try:
                turn = self.provider.chat_turn(model=model, system=system, messages=messages, tools=tool_specs,
                                               tool_choice=tool_choice, max_tokens=self.settings.llm_max_output_tokens, task=task)
            except (LLMUnavailable, LLMRequestError) as exc:
                self.telemetry.record(LLMCallRecord(
                    provider=self.provider.name, model=model, tier=tier, task=task, success=False,
                    latency_ms=int((time.perf_counter() - start) * 1000), error=f"{type(exc).__name__}: {exc.message}"))
                last_exc = exc
                status = exc.details.get("status") if isinstance(exc, LLMRequestError) else None
                retry_with_other_model = isinstance(exc, LLMUnavailable) or status in (400, 404)
                if retry_with_other_model and self.settings.llm_fallback_enabled:
                    log.warning("model %s failed for task %s; trying fallback", model, task)
                    continue
                raise
            latency = int((time.perf_counter() - start) * 1000)
            self.telemetry.record(LLMCallRecord(
                provider=self.provider.name, model=turn.model or model, tier=tier, task=task, success=True, latency_ms=latency,
                input_tokens=turn.usage.input_tokens, output_tokens=turn.usage.output_tokens,
                est_cost_usd=estimate_cost(self.settings, model, turn.usage.input_tokens, turn.usage.output_tokens)))
            return turn
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _user_message(user: str, images: list[dict[str, str]] | None) -> Message:
        if not images:
            return {"role": "user", "content": user}
        blocks: list[dict[str, Any]] = [{"type": "image", "media_type": i["media_type"], "data": i["data"]} for i in images]
        blocks.append({"type": "text", "text": user})
        return {"role": "user", "content": blocks}

    # ------------------------------------------------------------------ structured output
    def structured(self, task: str, schema: type[T], *, system: str, user: str, images: list[dict[str, str]] | None = None) -> T:
        tool = ToolSpec(name=final_tool_name(schema), description=f"Return the final {schema.__name__} result.",
                        input_schema=tool_schema(schema))
        full_system = f"{SYSTEM_GUARD}\n{system}"
        messages: list[Message] = [self._user_message(user, images)]
        error_text = ""
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            turn = self._turn(task, full_system, messages, [tool], tool_choice=tool.name)
            call = next((c for c in turn.tool_calls if c.name == tool.name), None)
            if call is None:
                error_text = "The model did not call the required output tool."
            else:
                try:
                    return schema.model_validate(call.input)
                except ValidationError as exc:
                    error_text = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
            if attempt < MAX_VALIDATION_RETRIES and call is not None:
                messages.append({"role": "assistant", "content": turn.blocks()})
                messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                                              "content": f"Validation failed: {error_text}. Call the tool again with corrected arguments."}]})
        raise LLMOutputError(f"The AI returned an invalid {schema.__name__} after retry: {error_text}")

    # ------------------------------------------------------------------ tool-using agent
    def run_agent(self, task: str, schema: type[T], *, system: str, user: str, tool_names: list[str], tool_ctx: ToolContext,
                  images: list[dict[str, str]] | None = None, max_steps: int = 6) -> T:
        if self.tools is None:
            raise ExternalServiceError("Tool registry is not configured")
        final = ToolSpec(name=final_tool_name(schema), description=f"Call this once, when finished, with the final {schema.__name__}.",
                         input_schema=tool_schema(schema))
        specs = [*self.tools.specs(tool_names), final]
        allowed = set(tool_names)
        full_system = f"{SYSTEM_GUARD}\n{system}"
        messages: list[Message] = [self._user_message(user, images)]
        validation_failures = 0
        for step in range(max_steps + 1):
            forced = step == max_steps  # out of steps: force the final answer
            turn = self._turn(task, full_system, messages, specs if not forced else [final],
                              tool_choice=final.name if forced else "any")
            final_call = next((c for c in turn.tool_calls if c.name == final.name), None)
            if final_call is not None:
                try:
                    return schema.model_validate(final_call.input)
                except ValidationError as exc:
                    validation_failures += 1
                    if validation_failures > MAX_VALIDATION_RETRIES:
                        raise LLMOutputError(f"The AI returned an invalid {schema.__name__}: {exc.errors()[0]['msg']}") from exc
                    messages.append({"role": "assistant", "content": turn.blocks()})
                    messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": final_call.id, "is_error": True,
                                                                  "content": "Validation failed: " + "; ".join(e["msg"] for e in exc.errors()[:4])}]})
                    continue
            if not turn.tool_calls:
                raise LLMOutputError("The AI stopped without calling a tool or returning a result.")
            messages.append({"role": "assistant", "content": turn.blocks()})
            results = []
            for call in turn.tool_calls:
                res = self.tools.execute(call.name, call.input, tool_ctx, caller="llm", allowed=allowed)
                results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": not res.ok,
                                "content": wrap_untrusted("tool_output", res.as_text(), tool=call.name)})
            messages.append({"role": "user", "content": results})
        raise LLMOutputError("The AI did not finish within the allowed number of steps.")


def context_block(data: dict[str, Any]) -> str:
    """Trusted, application-generated context. Numbers here come from deterministic code, not the model."""
    return "<context_json>\n" + json.dumps(data, default=str, ensure_ascii=False) + "\n</context_json>"
