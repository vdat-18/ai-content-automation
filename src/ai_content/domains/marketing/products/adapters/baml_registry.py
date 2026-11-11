"""Runtime BAML client registry for the products BAML functions."""

from __future__ import annotations

from baml_py import ClientRegistry


def build_client_registry(
    *,
    name: str,
    base_url: str,
    model: str,
    api_key: str,
    reasoning_effort: str | None,
    temperature: float | None,
    max_output_tokens: int | None = None,
) -> ClientRegistry:
    """Build the BAML client; model may list several names, comma separated, as fallbacks.

    Without max_output_tokens the model is not limited in how much it may answer.
    """
    models = [m.strip() for m in model.split(",") if m.strip()]
    registry = ClientRegistry()
    names: list[str] = []
    for position, one_model in enumerate(models):
        options: dict[str, object] = {
            "base_url": base_url,
            "model": one_model,
            "api_key": api_key,
            "stream": False,
        }
        if max_output_tokens is not None:
            options["max_tokens"] = max_output_tokens
        if reasoning_effort is not None:
            options["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            options["temperature"] = temperature
        client_name = name if position == 0 else f"{name}Fallback{position}"
        registry.add_llm_client(client_name, "openai-generic", options)
        names.append(client_name)
    if len(names) > 1:
        # Several models: try them in order, moving on when one errors (e.g. quota exhausted).
        registry.add_llm_client(f"{name}Chain", "fallback", {"strategy": names})
        registry.set_primary(f"{name}Chain")
    else:
        registry.set_primary(name)
    return registry


__all__ = ["build_client_registry"]
