"""Deterministic LLM *test double* (LLM_PROVIDER=mock).

This is NOT an AI model. It parses the prompt with regexes so the full application, tests and demos can
run offline. It is refused in production (see Settings.missing_required), every call is recorded with
provider='mock', and the UI shows a 'Mock AI' banner. It cannot interpret image pixels.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.categories.registry import PROFILES, keyword_classify
from app.llm.types import AssistantTurn, Message, ToolCall, ToolChoice, ToolSpec, Usage
from app.utils import text as T


def _flatten_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def _context(text: str) -> dict[str, Any]:
    m = re.search(r"<context_json>\s*(.*?)\s*</context_json>", text, re.S)
    return json.loads(m.group(1)) if m else {}


def _untrusted(text: str, kind: str = "user_input") -> str:
    parts = re.findall(rf"<untrusted_{kind}[^>]*>\s*(.*?)\s*</untrusted_{kind}>", text, re.S)
    return "\n".join(parts)


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._counter = 0

    def _id(self) -> str:
        self._counter += 1
        return f"mock_{self._counter}"

    def chat_turn(self, *, model: str, system: str, messages: list[Message], tools: list[ToolSpec] | None = None,
                  tool_choice: ToolChoice = "auto", max_tokens: int = 4096, task: str = "") -> AssistantTurn:
        first_user = next(m for m in messages if m["role"] == "user")
        text = _flatten_text(first_user["content"])
        ctx = _context(text)
        tool_names = [t.name for t in tools or []]
        final = next((n for n in tool_names if n.startswith("submit_")), None)
        schema = (final or "").removeprefix("submit_")

        # Tool-using scope planner: look up materials first, then submit.
        if schema == "ScopePlan" and len(messages) == 1 and "material_lookup" in tool_names and tool_choice == "any":
            calls = [ToolCall(self._id(), "material_lookup", {"group": g["group"], "tier": "standard"}) for g in ctx.get("groups", [])[:12]]
            return AssistantTurn(text="", tool_calls=calls, usage=Usage(0, 0), model=model)

        handler = getattr(self, f"_h_{schema}", None)
        if handler is None:
            return AssistantTurn(text="mock: no handler", tool_calls=[], usage=Usage(0, 0), model=model)
        payload = handler(text, ctx)
        return AssistantTurn(text="", tool_calls=[ToolCall(self._id(), final or "", payload)], usage=Usage(0, 0), model=model)

    # ----------------------------------------------------------------- handlers
    def _h_RoomVisionAnalysis(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall_confidence": 0.1,
            "limitations": ["Mock AI provider cannot interpret image pixels; only computed image statistics are available.",
                            "Dimensions cannot be measured from a photograph."],
            "dimensions": {"provenance": "unknown", "confidence": 0.0},
        }

    def _h_Requirements(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        raw = _untrusted(text) or text
        existing: dict[str, Any] = ctx.get("existing_requirements") or {}
        money = T.parse_money(raw)
        area = T.parse_area_sqm(raw)
        weeks = T.parse_timeline_weeks(raw)
        styles = T.find_styles(raw)
        rooms = T.find_rooms(raw)
        loc = T.find_location(raw)
        prop = T.find_property_type(raw)
        out: dict[str, Any] = {k: v for k, v in existing.items() if v not in (None, [], "")}
        prov = dict(out.get("provenance") or {})

        def put(key: str, value: Any) -> None:
            if value not in (None, [], ""):
                out[key] = value
                prov[key] = "user_provided"

        put("budget", {"amount": money[0], "currency": money[1]} if money else None)
        put("area_sqm", area)
        put("timeline_weeks", weeks)
        put("desired_style", styles[0] if styles else None)
        put("rooms", rooms or None)
        put("location", loc)
        put("property_type", prop)
        low = raw.lower()
        out.setdefault("project_type", "renovation" if any(w in low for w in ("renovat", "redo", "remodel", "upgrade", "makeover")) else None)
        must = [m.strip() for m in re.findall(r"(?:need|want|must have|include)\s+([a-z ,\-]{3,60})", low)][:6]
        if must:
            out["must_haves"] = list(dict.fromkeys([*(out.get("must_haves") or []), *must]))
        missing = [f for f, label in (("area_sqm", "room area"), ("budget", "budget"), ("location", "location"),
                                      ("timeline_weeks", "timeline"), ("desired_style", "style")) if not out.get(f)]
        out["missing_information"] = missing
        out["provenance"] = prov
        out["confidence"] = round(0.9 - 0.12 * len(missing), 2)
        return out

    def _h_ProjectClassification(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        key, conf = keyword_classify(_untrusted(text) or text)
        return {"category": key, "confidence": conf, "rationale": "Keyword match (mock provider)."}

    def _h_ClarificationQuestions(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        templates = {
            "area_sqm": "What is the approximate floor area of the space (in sq ft or sq m)?",
            "budget": "Do you have a budget range in mind?",
            "location": "Which city is the property in?",
            "timeline_weeks": "When would you like the work completed?",
            "desired_style": "Is there a design style you prefer (for example modern, minimalist, traditional)?",
        }
        qs = [templates[m] for m in ctx.get("missing", []) if m in templates][:4] or ["Is there anything else we should know?"]
        return {"questions": qs}

    def _h_ScopePlan(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        lines = []
        for g in ctx.get("groups", []):
            qty = g.get("default_quantity")
            if qty:
                lines.append({"group": g["group"], "quantity": qty, "unit": g["unit"], "optional": g.get("optional", False),
                              "rationale": "Default allowance for this category (mock provider).", "quantity_basis": "estimated"})
        return {"lines": lines, "assumptions": ["Quantities are category defaults scaled to the stated floor area (mock provider)."],
                "exclusions": ["Appliances, loose furniture and structural changes unless listed."], "evidence_ids": ctx.get("evidence_ids", [])[:5]}

    def _h_QuoteNarrative(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        p = ctx.get("pricing", {})
        std = p.get("standard_total")
        return {
            "summary": f"[mock-ai] {ctx.get('category_label', 'Renovation')} quote. Standard option estimated at "
                       f"{ctx.get('currency', '')} {std:,.0f} including tax and contingency. Estimate only; subject to site survey and approval." if std else "[mock-ai] Estimate only.",
            "assumptions": ctx.get("assumptions", [])[:6], "exclusions": ctx.get("exclusions", [])[:6],
            "risks": ctx.get("risk_notes", [])[:4] or ["Hidden conditions may change scope once work starts."],
            "tradeoffs": ctx.get("tradeoffs", [])[:6],
        }

    def _h_NegotiationConstraint(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        raw = _untrusted(text) or text
        money = T.parse_money(raw)
        weeks = T.parse_timeline_weeks(raw)
        low = raw.lower()
        return {"new_budget": {"amount": money[0], "currency": money[1]} if money else None, "timeline_weeks": weeks,
                "wants_cheaper": any(w in low for w in ("expensive", "cheaper", "too much", "lower", "reduce", "less")),
                "keep_priorities": list(T.find_rooms(raw)), "drop_candidates": [], "notes": raw[:200]}

    def _h_Recommendations(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        cat = ctx.get("category", "")
        items = [{"title": "Layered lighting plan", "detail": "Combine ambient, task and accent lighting; it changes how finishes read.", "kind": "design"}]
        if cat != "smart_home_upgrade":
            items.append({"title": "Add smart switches", "detail": "Retrofit smart switches during the electrical phase to avoid re-opening walls later.", "kind": "smart_home"})
        return {"items": items}

    def _h_ChatIntent(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        low = (_untrusted(text) or text).lower()
        waiting = ctx.get("awaiting_clarification")
        if waiting:
            intent = "clarification_answer"
        elif any(w in low for w in ("expensive", "budget", "cheaper", "too much", "lower the price", "discount")):
            intent = "negotiate"
        elif any(w in low for w in ("show me", "visuali", "render", "what would it look like")):
            intent = "visualize"
        elif any(w in low for w in ("suggest", "idea", "recommend", "not sure", "don't know", "what should")):
            intent = "suggest"
        elif any(w in low for w in ("add ", "also want", "change the", "instead", "include")):
            intent = "replan"
        elif "?" in low:
            intent = "question"
        else:
            intent = "other"
        return {"intent": intent, "confidence": 0.6}

    def _h_AnswerText(self, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"answer": "[mock-ai] I can only answer from the project data. Please review the quote and requirements tabs."}


__all__ = ["PROFILES", "MockProvider"]
