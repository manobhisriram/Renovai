"""Task -> tier -> model routing. No model id is hard-coded outside Settings."""

from __future__ import annotations

from app.config import Settings
from app.llm.types import Tier

DEFAULT_TASK_TIERS: dict[str, Tier] = {
    # SIMPLE: cheap, fast, low-risk
    "intent_classification": "simple",
    "project_classification": "simple",
    "clarification_questions": "simple",
    "acknowledgement": "simple",
    # MEDIUM: structured extraction, perception, recommendations, dialogue
    "requirements_extraction": "medium",
    "vision_analysis": "medium",
    "recommendations": "medium",
    "negotiation_parse": "medium",
    "qa": "medium",
    # COMPLEX: reasoning over evidence where mistakes are expensive
    "scope_planning": "complex",
    "quote_reasoning": "complex",
    "conflict_resolution": "complex",
}
FALLBACK_ORDER: dict[Tier, list[Tier]] = {"complex": ["medium", "simple"], "medium": ["simple"], "simple": []}


class ModelRouter:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._overrides = settings.task_tier_overrides
        self._models: dict[Tier, str] = {
            "simple": settings.llm_model_simple, "medium": settings.llm_model_medium, "complex": settings.llm_model_complex,
        }

    def tier_for(self, task: str) -> Tier:
        tier = self._overrides.get(task) or DEFAULT_TASK_TIERS.get(task, "medium")
        return tier  # type: ignore[return-value]

    def model_for(self, tier: Tier) -> str:
        return self._models[tier]

    def candidates(self, task: str) -> list[tuple[Tier, str]]:
        """Primary model first, then (optionally) cheaper fallbacks, de-duplicated by model id."""
        tier = self.tier_for(task)
        out: list[tuple[Tier, str]] = [(tier, self._models[tier])]
        if self._settings.llm_fallback_enabled:
            for alt in FALLBACK_ORDER[tier]:
                if self._models[alt] not in {m for _, m in out}:
                    out.append((alt, self._models[alt]))
        return out

    def describe(self) -> dict[str, object]:
        return {"provider": self._settings.llm_provider, "models": dict(self._models),
                "task_tiers": {**DEFAULT_TASK_TIERS, **self._overrides}, "fallback_enabled": self._settings.llm_fallback_enabled}
