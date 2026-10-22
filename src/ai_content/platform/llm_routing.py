"""Approved dashboard-selectable LLM routes."""

# Router provider prefix for each approved model.
AGENT_MODEL_PROVIDERS: dict[str, str] = {
    "grok-4-fast-reasoning": "xai",
    "grok-4.7": "xai",
}

APPROVED_AGENT_MODELS: tuple[str, ...] = tuple(AGENT_MODEL_PROVIDERS)

# Models that older persisted jobs may reference; they can be read but not selected.
RETIRED_AGENT_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)

DEFAULT_AGENT_MODEL = "grok-4-fast-reasoning"
DEFAULT_RESEARCH_MODEL = "grok-4-fast-reasoning"
DEFAULT_AGENT_REASONING_LEVEL = "auto"

# Grok routes do not support a reasoning effort, so only "auto" is offered.
AGENT_REASONING_LEVELS: dict[str, tuple[str, ...]] = dict.fromkeys(APPROVED_AGENT_MODELS, ("auto",))


def normalize_persisted_agent_model_id(model: str) -> str:
    """Normalize a known router prefix while reading persisted records."""

    normalized = model.strip()
    _, _, direct_model = normalized.rpartition("/")
    return direct_model if direct_model in APPROVED_AGENT_MODELS else normalized


def require_approved_agent_model(model: str) -> str:
    """Return a normalized model ID or reject routes not approved for the dashboard."""

    normalized = model.strip()
    if normalized not in APPROVED_AGENT_MODELS:
        raise ValueError("Agent model is not approved for dashboard selection")
    return normalized


def route_approved_agent_model(model: str, *, configured_model: str) -> str:
    """Route a dashboard-selected model through the configured provider.

    A configured model without a prefix is a direct provider client, so the bare ID is
    returned; otherwise the model's router provider prefix is applied.
    """

    approved_model = require_approved_agent_model(model)
    if "/" not in configured_model:
        return approved_model
    return f"{AGENT_MODEL_PROVIDERS[approved_model]}/{approved_model}"


def require_supported_agent_reasoning_level(model: str, level: str) -> str:
    """Return a normalized reasoning level supported by the selected model."""

    normalized = level.strip().lower()
    if normalized not in AGENT_REASONING_LEVELS[require_approved_agent_model(model)]:
        raise ValueError("Agent reasoning level is not supported by the selected model")
    return normalized


__all__ = [
    "AGENT_MODEL_PROVIDERS",
    "APPROVED_AGENT_MODELS",
    "AGENT_REASONING_LEVELS",
    "DEFAULT_AGENT_MODEL",
    "DEFAULT_AGENT_REASONING_LEVEL",
    "DEFAULT_RESEARCH_MODEL",
    "RETIRED_AGENT_MODELS",
    "normalize_persisted_agent_model_id",
    "require_approved_agent_model",
    "route_approved_agent_model",
    "require_supported_agent_reasoning_level",
]
