from pathlib import Path

import pytest

from ai_content.platform.llm_routing import (
    APPROVED_AGENT_MODELS,
    DEFAULT_AGENT_MODEL,
    normalize_persisted_agent_model_id,
    require_approved_agent_model,
    require_supported_agent_reasoning_level,
    route_approved_agent_model,
)


def test_only_grok_models_are_approved() -> None:
    assert DEFAULT_AGENT_MODEL == "grok-4-fast-reasoning"
    assert all(model.startswith("grok-") for model in APPROVED_AGENT_MODELS)
    with pytest.raises(ValueError):
        require_approved_agent_model("gemini-2.5-flash")


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


def test_grok_only_offers_auto_reasoning() -> None:
    assert require_supported_agent_reasoning_level("grok-4.7", "auto") == "auto"
    with pytest.raises(ValueError):
        require_supported_agent_reasoning_level("grok-4.7", "high")


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
    with pytest.raises(ValueError):
        require_approved_agent_model("gemini-2.5-flash")
