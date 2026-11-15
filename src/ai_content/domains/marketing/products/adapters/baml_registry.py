"""Runtime BAML client registry for the products BAML functions."""

from __future__ import annotations

import re

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
    """Build the BAML client for one model; a failing call raises, with no fallback model.

    Without max_output_tokens the model is not limited in how much it may answer.
    """
    options: dict[str, object] = {
        "base_url": base_url,
        "model": model.strip(),
        "api_key": api_key,
        "stream": False,
    }
    if max_output_tokens is not None:
        options["max_tokens"] = max_output_tokens
    if reasoning_effort is not None:
        options["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        options["temperature"] = temperature
    # The model is part of the client name, so every error names the model that failed.
    client_name = f"{name}_{re.sub(r'[^A-Za-z0-9.-]', '_', str(options['model']))}"
    registry = ClientRegistry()
    registry.add_llm_client(client_name, "openai-generic", options)
    registry.set_primary(client_name)
    return registry


__all__ = ["build_client_registry"]
