from __future__ import annotations

import pytest

from app.config import ConfigurationError
from app.llm.router import DEFAULT_TASK_TIERS, ModelRouter
from tests.conftest import make_settings


def test_default_task_routing(tmp_path):
    r = ModelRouter(make_settings(tmp_path))
    assert r.tier_for("intent_classification") == "simple"
    assert r.tier_for("requirements_extraction") == "medium" and r.tier_for("vision_analysis") == "medium"
    assert r.tier_for("quote_reasoning") == "complex" and r.tier_for("scope_planning") == "complex"
    assert r.tier_for("some_new_task") == "medium"  # safe default


def test_model_ids_come_from_configuration_not_code(tmp_path):
    s = make_settings(tmp_path, llm_model_simple="small-x", llm_model_medium="mid-y", llm_model_complex="big-z")
    r = ModelRouter(s)
    assert [r.model_for(t) for t in ("simple", "medium", "complex")] == ["small-x", "mid-y", "big-z"]


def test_overrides_and_fallback_order(tmp_path):
    s = make_settings(tmp_path, llm_task_tier_overrides='{"vision_analysis": "complex"}')
    r = ModelRouter(s)
    assert r.tier_for("vision_analysis") == "complex"
    assert [t for t, _ in r.candidates("vision_analysis")] == ["complex", "medium", "simple"]
    assert [t for t, _ in r.candidates("intent_classification")] == ["simple"]


def test_fallback_can_be_disabled_and_dedupes_models(tmp_path):
    r = ModelRouter(make_settings(tmp_path, llm_fallback_enabled=False))
    assert len(r.candidates("quote_reasoning")) == 1
    same = ModelRouter(make_settings(tmp_path, llm_model_simple="m", llm_model_medium="m", llm_model_complex="m"))
    assert len(same.candidates("quote_reasoning")) == 1


def test_invalid_override_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError):
        ModelRouter(make_settings(tmp_path, llm_task_tier_overrides='{"qa": "gigantic"}'))
    with pytest.raises(ConfigurationError):
        make_settings(tmp_path, llm_task_tier_overrides="not json").task_tier_overrides  # noqa: B018


def test_every_default_task_maps_to_a_valid_tier():
    assert set(DEFAULT_TASK_TIERS.values()) <= {"simple", "medium", "complex"}
