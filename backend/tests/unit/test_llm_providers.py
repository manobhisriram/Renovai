from __future__ import annotations

import json

import httpx
import pytest

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.client import LLMClient
from app.llm.openai_provider import OpenAICompatProvider
from app.llm.router import ModelRouter
from app.llm.types import ToolSpec
from app.observability.telemetry import Telemetry
from app.schemas.ai import ClarificationQuestions
from app.tools.registry import ToolRegistry
from app.utils.errors import LLMOutputError, LLMRequestError, LLMUnavailable, ServiceNotConfigured
from tests.conftest import make_settings


def anthropic(tmp_path, handler, **over):
    s = make_settings(tmp_path, llm_provider="anthropic", anthropic_api_key="sk-ant-test-key-123456", llm_max_retries=3, **over)
    return s, AnthropicProvider(s, client=httpx.Client(transport=httpx.MockTransport(handler)))


TOOL = ToolSpec("submit_X", "d", {"type": "object", "properties": {"a": {"type": "string"}}})


def tool_use_response(payload, model="claude-x"):
    return httpx.Response(200, json={"model": model, "stop_reason": "tool_use", "usage": {"input_tokens": 11, "output_tokens": 7},
                                     "content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "tu_1", "name": "submit_X", "input": payload}]})


def test_anthropic_request_shape_and_parsing(tmp_path):
    seen = {}

    def handler(req: httpx.Request):
        seen["headers"], seen["body"], seen["url"] = dict(req.headers), json.loads(req.content), str(req.url)
        return tool_use_response({"a": "b"})

    _, p = anthropic(tmp_path, handler)
    turn = p.chat_turn(model="claude-m", system="sys", messages=[{"role": "user", "content": [
        {"type": "image", "media_type": "image/jpeg", "data": "AAA"}, {"type": "text", "text": "look"}]}], tools=[TOOL], tool_choice="submit_X", max_tokens=500)
    b = seen["body"]
    assert seen["url"].endswith("/v1/messages") and seen["headers"]["x-api-key"] == "sk-ant-test-key-123456"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert b["model"] == "claude-m" and b["max_tokens"] == 500 and b["system"] == "sys"
    assert b["tool_choice"] == {"type": "tool", "name": "submit_X"} and b["tools"][0]["input_schema"]["type"] == "object"
    assert b["messages"][0]["content"][0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA"}}
    assert "temperature" not in b and "top_p" not in b, "sampling params must not be sent"
    assert turn.tool_calls[0].input == {"a": "b"} and turn.usage.input_tokens == 11 and turn.usage.output_tokens == 7


def test_anthropic_retries_overload_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.resilience.time.sleep", lambda _: None)
    n = {"c": 0}

    def handler(_):
        n["c"] += 1
        return httpx.Response(529, json={"error": {"message": "overloaded"}}) if n["c"] < 3 else tool_use_response({"a": "ok"})

    _, p = anthropic(tmp_path, handler)
    assert p.chat_turn(model="m", system="s", messages=[{"role": "user", "content": "x"}], tools=[TOOL], tool_choice="any").tool_calls
    assert n["c"] == 3


def test_anthropic_gives_up_after_max_retries_and_4xx_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.resilience.time.sleep", lambda _: None)
    n = {"c": 0}

    def always_503(_):
        n["c"] += 1
        return httpx.Response(503)

    _, p = anthropic(tmp_path, always_503)
    with pytest.raises(LLMUnavailable):
        p.chat_turn(model="m", system="s", messages=[{"role": "user", "content": "x"}])
    assert n["c"] == 3

    n["c"] = 0

    def bad_request(_):
        n["c"] += 1
        return httpx.Response(400, json={"error": {"message": "bad model"}})

    _, p2 = anthropic(tmp_path, bad_request)
    with pytest.raises(LLMRequestError) as e:
        p2.chat_turn(model="m", system="s", messages=[{"role": "user", "content": "x"}])
    assert n["c"] == 1 and "bad model" in e.value.message and "sk-ant" not in e.value.message


def test_missing_key_gives_actionable_error(tmp_path):
    s = make_settings(tmp_path, llm_provider="anthropic")
    with pytest.raises(ServiceNotConfigured, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(s).chat_turn(model="m", system="s", messages=[{"role": "user", "content": "x"}])


def make_client(tmp_path, provider_handler, **over):
    s, prov = anthropic(tmp_path, provider_handler, **over)
    router = ModelRouter(s)
    sunk = []
    tele = Telemetry([type("S", (), {"record": lambda self, r: sunk.append(r)})()])
    return LLMClient(s, prov, router, tele, ToolRegistry()), sunk


def test_structured_retries_once_on_invalid_output_then_succeeds(tmp_path):
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        name = body["tools"][0]["name"]
        payload = {"questions": []} if len(calls) == 1 else {"questions": ["Which city?"]}  # empty violates min_length=1
        return httpx.Response(200, json={"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1},
                                         "content": [{"type": "tool_use", "id": f"t{len(calls)}", "name": name, "input": payload}]})

    client, sunk = make_client(tmp_path, handler)
    res = client.structured("clarification_questions", ClarificationQuestions, system="s", user="u")
    assert res.questions == ["Which city?"] and len(calls) == 2
    retry_msgs = calls[1]["messages"]
    assert retry_msgs[-1]["content"][0]["type"] == "tool_result" and retry_msgs[-1]["content"][0]["is_error"] is True
    assert len(sunk) == 2 and all(r.success and r.tier == "simple" for r in sunk)


def test_structured_raises_after_second_invalid_output(tmp_path):
    def handler(req):
        name = json.loads(req.content)["tools"][0]["name"]
        return httpx.Response(200, json={"model": "m", "usage": {}, "content": [{"type": "tool_use", "id": "t", "name": name, "input": {"questions": []}}]})

    client, _ = make_client(tmp_path, handler)
    with pytest.raises(LLMOutputError):
        client.structured("clarification_questions", ClarificationQuestions, system="s", user="u")


def test_model_fallback_on_unavailable_and_telemetry_records_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.resilience.time.sleep", lambda _: None)
    models = []

    def handler(req):
        body = json.loads(req.content)
        models.append(body["model"])
        if body["model"] == "big-model":
            return httpx.Response(503)
        return httpx.Response(200, json={"model": body["model"], "usage": {"input_tokens": 5, "output_tokens": 2},
                                         "content": [{"type": "tool_use", "id": "t", "name": body["tools"][0]["name"], "input": {"questions": ["q?"]}}]})

    client, sunk = make_client(tmp_path, handler, llm_model_complex="big-model", llm_model_medium="mid-model")
    client.router._overrides = {"clarification_questions": "complex"}
    assert client.structured("clarification_questions", ClarificationQuestions, system="s", user="u").questions == ["q?"]
    assert models[-1] == "mid-model" and "big-model" in models
    assert [r.success for r in sunk] == [False, True] and "LLMUnavailable" in (sunk[0].error or "")


def test_openai_compat_conversion_and_parsing(tmp_path):
    seen = {}

    def handler(req):
        seen["body"], seen["auth"] = json.loads(req.content), req.headers["authorization"]
        return httpx.Response(200, json={"model": "gpt-x", "usage": {"prompt_tokens": 9, "completion_tokens": 4}, "choices": [{
            "finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"id": "c1", "type": "function",
                                                                                          "function": {"name": "submit_X", "arguments": '{"a": "z"}'}}]}}]})

    s = make_settings(tmp_path, llm_provider="openai", openai_api_key="sk-openai-test-key-123", openai_base_url="http://localhost:11434/v1")
    p = OpenAICompatProvider(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    msgs = [{"role": "user", "content": [{"type": "image", "media_type": "image/png", "data": "QQ=="}, {"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "c0", "name": "material_lookup", "input": {"group": "x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c0", "content": "{}"}]}]
    turn = p.chat_turn(model="gpt-x", system="sys", messages=msgs, tools=[TOOL], tool_choice="submit_X")
    b = seen["body"]
    assert seen["auth"].startswith("Bearer sk-openai") and b["messages"][0] == {"role": "system", "content": "sys"}
    assert b["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert b["messages"][2]["tool_calls"][0]["function"]["name"] == "material_lookup" and b["messages"][3]["role"] == "tool"
    assert b["tool_choice"] == {"type": "function", "function": {"name": "submit_X"}}
    assert turn.tool_calls[0].input == {"a": "z"} and turn.usage.output_tokens == 4
