from __future__ import annotations

import time

from pydantic import BaseModel, Field

from app.tools.registry import ToolContext, ToolDef, ToolRegistry
from app.utils.errors import ForbiddenError


class In(BaseModel):
    n: int = Field(ge=0, le=10)


def reg() -> ToolRegistry:
    r = ToolRegistry(default_timeout_s=0.3)
    r.register(ToolDef("double", "doubles", In, lambda ctx, a: {"v": a.n * 2}))
    r.register(ToolDef("write_db", "writes", In, lambda ctx, a: {"wrote": a.n}, llm_exposed=False, side_effect=True))
    r.register(ToolDef("slow", "sleeps", In, lambda ctx, a: time.sleep(2) or {"v": 1}))
    r.register(ToolDef("boom", "raises", In, lambda ctx, a: (_ for _ in ()).throw(RuntimeError("kaput secret-detail"))))
    return r


CTX = ToolContext(deps=None)


def test_valid_call_and_typed_validation():
    r = reg()
    ok = r.execute("double", {"n": 4}, CTX, caller="llm")
    assert ok.ok and ok.output == {"v": 8}
    bad = r.execute("double", {"n": 99}, CTX, caller="llm")
    assert not bad.ok and "invalid arguments" in bad.error and "n" in bad.error
    assert not r.execute("double", {"n": "abc"}, CTX, caller="llm").ok
    assert not r.execute("double", {}, CTX, caller="llm").ok


def test_llm_cannot_call_app_only_or_unlisted_tools():
    r = reg()
    assert not r.execute("write_db", {"n": 1}, CTX, caller="llm").ok
    assert r.execute("write_db", {"n": 1}, CTX, caller="app").ok
    assert not r.execute("double", {"n": 1}, CTX, caller="llm", allowed={"other"}).ok
    assert not r.execute("nope", {}, CTX, caller="llm").ok
    try:
        r.specs(["write_db"])
    except ForbiddenError:
        pass
    else:
        raise AssertionError("side-effect tools must never be offered to the model")


def test_timeout_and_exception_are_contained():
    r = reg()
    t = r.execute("slow", {"n": 1}, CTX, caller="app")
    assert not t.ok and "timed out" in t.error
    e = r.execute("boom", {"n": 1}, CTX, caller="app")
    assert not e.ok and "RuntimeError" in e.error


def test_specs_expose_json_schema_for_exposed_tools():
    spec = reg().specs(["double"])[0]
    assert spec.name == "double" and spec.input_schema["properties"]["n"]["maximum"] == 10
