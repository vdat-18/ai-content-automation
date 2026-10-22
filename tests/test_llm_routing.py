import pytest

from ai_content.platform.llm_routing import (
    DEFAULT_AGENT_MODEL,
    normalize_persisted_agent_model_id,
    require_supported_agent_reasoning_level,
    route_approved_agent_model,
)


def test_default_agent_model_is_grok() -> None:
    assert DEFAULT_AGENT_MODEL == "grok-4-fast-reasoning"


@pytest.mark.parametrize(
    ("model", "configured", "expected"),
    [
        ("grok-4.7", "xai/grok-4.7", "xai/grok-4.7"),
        ("grok-4-fast-reasoning", "gemini/gemini-2.5-flash", "xai/grok-4-fast-reasoning"),
        ("gemini-3.8-flash", "xai/grok-4.7", "gemini/gemini-3.8-flash"),
        ("gemini-3.8-flash", "gc/gemini-2.5-flash", "gc/gemini-3.8-flash"),
        ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.8-flash"),
    ],
)
def test_route_uses_the_selected_models_provider(model, configured, expected) -> None:
    assert route_approved_agent_model(model, configured_model=configured) == expected


def test_grok_only_offers_auto_reasoning() -> None:
    assert require_supported_agent_reasoning_level("grok-4.7", "auto") == "auto"
    with pytest.raises(ValueError):
        require_supported_agent_reasoning_level("grok-4.7", "high")


def test_persisted_router_prefixes_are_normalized() -> None:
    assert normalize_persisted_agent_model_id("xai/grok-4.7") == "grok-4.7"
    assert normalize_persisted_agent_model_id("gemini/gemini-2.5-flash") == "gemini-2.5-flash"
    assert normalize_persisted_agent_model_id("openai/gpt-5") == "openai/gpt-5"


def test_preparation_override_routes_dashboard_model() -> None:
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src/ai_content/entrypoints/api/creative_automation.py"
    ).read_text(encoding="utf-8")
    assert '"model": request.agent_model_id or preparation_config.model' not in source
    assert "configured_model=preparation_config.model" in source
