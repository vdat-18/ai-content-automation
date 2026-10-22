"""Readiness probe for an opt-in OpenAI-compatible preparation model."""

from __future__ import annotations

from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict

from ..config.preparation import PreparationConfig
from ..ports.preparation import PreparationError


class _ModelEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str


class _ModelCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: tuple[_ModelEntry, ...]


async def probe_preparation_model(
    config: PreparationConfig,
    api_key: str | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Verify that the configured endpoint exposes the selected model route."""
    if config.backend != "baml" or not config.probe_on_startup:
        return
    if config.api_key_env and not api_key:
        raise PreparationError(
            "Configured model credential environment variable is missing",
            "model_credentials_missing",
        )

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = urljoin(config.base_url.rstrip("/") + "/", "models")
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(config.probe_timeout_seconds),
        ) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            catalog = _ModelCatalog.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as error:
        raise PreparationError(
            "Preparation model endpoint readiness check failed",
            "model_readiness_failed",
        ) from error

    if config.model not in {entry.id for entry in catalog.data}:
        raise PreparationError(
            "Configured preparation model is not available from the endpoint",
            "model_route_unavailable",
        )


__all__ = ["probe_preparation_model"]
