"""Approved dashboard-selectable LLM routes."""

APPROVED_AGENT_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)

DEFAULT_AGENT_MODEL = "gemini-2.5-flash"
DEFAULT_RESEARCH_MODEL = "gemini-2.5-flash"
DEFAULT_AGENT_REASONING_LEVEL = "auto"

AGENT_REASONING_LEVELS: dict[str, tuple[str, ...]] = {
    "gemini-3.8-flash": ("auto", "low", "medium", "high"),
    "gemini-3.7-flash": ("auto", "low", "medium", "high"),
    "gemini-3.6-flash": ("auto", "minimal", "low", "medium", "high"),
    "gemini-3.5-flash": ("auto", "low", "medium", "high"),
    "gemini-2.5-flash": ("auto", "low", "medium", "high"),
}


def normalize_persisted_agent_model_id(model: str) -> str:
    """Normalize a known legacy route prefix while reading persisted records."""

    normalized = model.strip()
    direct_model = normalized.removeprefix("gemini/")
    return direct_model if direct_model in APPROVED_AGENT_MODELS else normalized


def require_approved_agent_model(model: str) -> str:
    """Return a normalized model ID or reject routes not approved for the dashboard."""

    normalized = model.strip()
    if normalized not in APPROVED_AGENT_MODELS:
        raise ValueError("Agent model is not approved for dashboard selection")
    return normalized


def route_approved_agent_model(model: str, *, configured_model: str) -> str:
    """Apply the configured provider prefix to a dashboard-selected model."""

    approved_model = require_approved_agent_model(model)
    provider_prefix, separator, configured_route = configured_model.rpartition("/")
    if separator and configured_route in APPROVED_AGENT_MODELS:
        return f"{provider_prefix}/{approved_model}"
    return approved_model


def require_supported_agent_reasoning_level(model: str, level: str) -> str:
    """Return a normalized reasoning level supported by the selected model."""

    normalized = level.strip().lower()
    if normalized not in AGENT_REASONING_LEVELS[require_approved_agent_model(model)]:
        raise ValueError("Agent reasoning level is not supported by the selected model")
    return normalized


__all__ = [
    "APPROVED_AGENT_MODELS",
    "AGENT_REASONING_LEVELS",
    "DEFAULT_AGENT_MODEL",
    "DEFAULT_AGENT_REASONING_LEVEL",
    "DEFAULT_RESEARCH_MODEL",
    "normalize_persisted_agent_model_id",
    "require_approved_agent_model",
    "route_approved_agent_model",
    "require_supported_agent_reasoning_level",
]
