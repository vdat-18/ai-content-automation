from pathlib import Path

import pytest

from ai_content.platform.llm_routing import (
    DEFAULT_AGENT_MODEL,
    normalize_persisted_agent_model_id,
    require_approved_agent_model,
    require_supported_agent_reasoning_level,
    route_approved_agent_model,
)


def test_models_are_accepted_flexibly() -> None:
    assert DEFAULT_AGENT_MODEL == "grok-4-fast-reasoning"
    assert require_approved_agent_model("gemini-2.5-flash") == "gemini-2.5-flash"
    assert require_approved_agent_model("gpt-4o") == "gpt-4o"
    with pytest.raises(ValueError):
        require_approved_agent_model("")


@pytest.mark.parametrize(
    ("model", "configured", "expected"),
    [
        ("grok-4.7", "xai/grok-4-fast-reasoning", "xai/grok-4.7"),
        ("grok-4-fast-reasoning", "gemini/gemini-2.5-flash", "xai/grok-4-fast-reasoning"),
        ("grok-4.7", "grok-4-fast-reasoning", "grok-4.7"),
    ],
)
def test_route_applies_the_router_prefix(model, configured, expected) -> None:
    assert route_approved_agent_model(model, configured_model=configured) == expected


def test_reasoning_level_normalization() -> None:
    assert require_supported_agent_reasoning_level("grok-4.7", "auto") == "auto"
    assert require_supported_agent_reasoning_level("grok-4.7", "high") == "high"


def test_persisted_router_prefixes_are_normalized() -> None:
    assert normalize_persisted_agent_model_id("xai/grok-4.7") == "grok-4.7"
    assert normalize_persisted_agent_model_id("openai/gpt-5") == "openai/gpt-5"


def test_preparation_override_routes_dashboard_model() -> None:
    source = (
        Path(__file__).parents[1] / "src/ai_content/entrypoints/api/creative_automation.py"
    ).read_text(encoding="utf-8")
    assert "configured_model=preparation_config.model" in source


def test_jobs_saved_with_a_retired_model_still_load() -> None:
    from ai_content.platform.llm_routing import RETIRED_AGENT_MODELS

    assert "gemini-2.5-flash" in RETIRED_AGENT_MODELS
    assert require_approved_agent_model("gemini-2.5-flash") == "gemini-2.5-flash"
