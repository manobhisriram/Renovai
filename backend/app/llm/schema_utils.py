"""JSON-schema helpers: inline $refs so every provider accepts tool schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP_KEYS = {"title", "$defs", "definitions", "examples"}


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            merged = {**_resolve(defs[name], defs), **{k: v for k, v in node.items() if k != "$ref"}}
            return merged
        return {k: _resolve(v, defs) for k, v in node.items() if k not in _DROP_KEYS or k in ("properties",)}
    if isinstance(node, list):
        return [_resolve(v, defs) for v in node]
    return node


def tool_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    schema = _resolve({k: v for k, v in raw.items() if k != "$defs"}, defs)
    schema.setdefault("type", "object")
    return schema
