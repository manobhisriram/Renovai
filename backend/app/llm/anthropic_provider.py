"""Anthropic Messages API provider (raw HTTP; no SDK coupling).

Only the minimal, stable request surface is used (model, max_tokens, system, messages, tools,
tool_choice). Sampling parameters are intentionally NOT sent: some current models restrict them.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.llm.types import AssistantTurn, Message, ToolCall, ToolChoice, ToolSpec, Usage
from app.utils.errors import LLMRequestError, LLMUnavailable, ServiceNotConfigured
from app.utils.resilience import CircuitBreaker, CircuitOpenError, retry_call

log = logging.getLogger(__name__)
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0))
        self._breaker = CircuitBreaker("anthropic", failure_threshold=6, reset_timeout=30.0)

    def _headers(self) -> dict[str, str]:
        key = self._settings.anthropic_api_key
        if key is None:
            raise ServiceNotConfigured("ANTHROPIC_API_KEY is not set. Add it to your environment (.env) to enable AI features.")
        return {"x-api-key": key.get_secret_value(), "anthropic-version": self._settings.anthropic_version,
                "content-type": "application/json"}

    @staticmethod
    def _convert_content(content: Any) -> Any:
        if isinstance(content, str):
            return content
        out: list[dict[str, Any]] = []
        for b in content:
            if b["type"] == "image":
                out.append({"type": "image", "source": {"type": "base64", "media_type": b["media_type"], "data": b["data"]}})
            elif b["type"] == "tool_result":
                out.append({"type": "tool_result", "tool_use_id": b["tool_use_id"], "content": b["content"],
                            **({"is_error": True} if b.get("is_error") else {})})
            else:
                out.append(b)
        return out

    def chat_turn(self, *, model: str, system: str, messages: list[Message], tools: list[ToolSpec] | None = None,
                  tool_choice: ToolChoice = "auto", max_tokens: int = 4096, task: str = "") -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": m["role"], "content": self._convert_content(m["content"])} for m in messages],
        }
        if tools:
            payload["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
            if tool_choice == "auto":
                payload["tool_choice"] = {"type": "auto"}
            elif tool_choice == "any":
                payload["tool_choice"] = {"type": "any"}
            else:
                payload["tool_choice"] = {"type": "tool", "name": tool_choice}
        url = self._settings.anthropic_base_url.rstrip("/") + "/v1/messages"
        headers = self._headers()

        def _call() -> dict[str, Any]:
            try:
                resp = self._client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                raise LLMUnavailable("The AI provider timed out.") from exc
            except httpx.TransportError as exc:
                raise LLMUnavailable("Could not reach the AI provider.") from exc
            if resp.status_code in RETRYABLE_STATUS:
                raise LLMUnavailable(f"The AI provider is temporarily unavailable (HTTP {resp.status_code}).")
            if resp.status_code >= 400:
                detail = _error_message(resp)
                raise LLMRequestError(f"AI provider rejected the request (HTTP {resp.status_code}): {detail}",
                                      details={"status": resp.status_code})
            return resp.json()

        try:
            data = retry_call(_call, attempts=self._settings.llm_max_retries, retry_on=(LLMUnavailable,), breaker=self._breaker)
        except CircuitOpenError as exc:
            raise LLMUnavailable("The AI provider is failing repeatedly; calls are paused briefly.") from exc

        text_parts, calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"], input=block.get("input") or {}))
        usage = data.get("usage") or {}
        return AssistantTurn(text="".join(text_parts), tool_calls=calls, stop_reason=data.get("stop_reason"),
                             usage=Usage(usage.get("input_tokens"), usage.get("output_tokens")), model=data.get("model", model))


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error", {}).get("message", ""))[:300]
    except Exception:
        return resp.text[:200]
