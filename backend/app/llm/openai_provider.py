"""OpenAI-compatible Chat Completions provider.

Works with OpenAI and with any server that speaks the same protocol (vLLM, Ollama, LM Studio, ...) by
setting OPENAI_BASE_URL — this is the 'local / open-source models' path.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.llm.anthropic_provider import RETRYABLE_STATUS, _error_message
from app.llm.types import AssistantTurn, Message, ToolCall, ToolChoice, ToolSpec, Usage
from app.utils.errors import LLMRequestError, LLMUnavailable, ServiceNotConfigured
from app.utils.resilience import CircuitBreaker, CircuitOpenError, retry_call


class OpenAICompatProvider:
    name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0))
        self._breaker = CircuitBreaker("openai", failure_threshold=6, reset_timeout=30.0)

    @staticmethod
    def _convert_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                text = "".join(b["text"] for b in content if b["type"] == "text")
                calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in content if b["type"] == "tool_use"]
                msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            parts: list[dict[str, Any]] = []
            for b in content:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                elif b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b["type"] == "image":
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{b['media_type']};base64,{b['data']}"}})
            if parts:
                out.append({"role": "user", "content": parts})
        return out

    def chat_turn(self, *, model: str, system: str, messages: list[Message], tools: list[ToolSpec] | None = None,
                  tool_choice: ToolChoice = "auto", max_tokens: int = 4096, task: str = "") -> AssistantTurn:
        key = self._settings.openai_api_key
        if key is None:
            raise ServiceNotConfigured("OPENAI_API_KEY is not set. Add it to your environment (.env), or set LLM_PROVIDER=anthropic.")
        payload: dict[str, Any] = {"model": model, "messages": self._convert_messages(system, messages), "max_tokens": max_tokens}
        if tools:
            payload["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
            payload["tool_choice"] = (
                "auto" if tool_choice == "auto" else "required" if tool_choice == "any"
                else {"type": "function", "function": {"name": tool_choice}}
            )
        url = self._settings.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key.get_secret_value()}", "Content-Type": "application/json"}

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
                raise LLMRequestError(f"AI provider rejected the request (HTTP {resp.status_code}): {_error_message(resp)}",
                                      details={"status": resp.status_code})
            return resp.json()

        try:
            data = retry_call(_call, attempts=self._settings.llm_max_retries, retry_on=(LLMUnavailable,), breaker=self._breaker)
        except CircuitOpenError as exc:
            raise LLMUnavailable("The AI provider is failing repeatedly; calls are paused briefly.") from exc

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], input=args))
        usage = data.get("usage") or {}
        return AssistantTurn(text=msg.get("content") or "", tool_calls=calls, stop_reason=choice.get("finish_reason"),
                             usage=Usage(usage.get("prompt_tokens"), usage.get("completion_tokens")), model=data.get("model", model))
