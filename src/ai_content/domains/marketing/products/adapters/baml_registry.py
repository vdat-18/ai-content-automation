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
    max_output_tokens: int,
) -> ClientRegistry:
    options: dict[str, object] = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "max_tokens": max_output_tokens,
        "stream": False,
    }
    if reasoning_effort is not None:
        options["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        options["temperature"] = temperature
    registry = ClientRegistry()
    registry.add_llm_client(name, "openai-generic", options)
    registry.set_primary(name)
    return registry


__all__ = ["build_client_registry"]
