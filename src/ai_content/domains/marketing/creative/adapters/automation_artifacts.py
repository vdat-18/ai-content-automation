"""Durable artifact for one Marketing-selected production-ready Creative package."""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from ai_content.domains.marketing.creative.ports.automation_workflow import (
    MarketingCreativeAutomationState,
)
from ai_content.domains.marketing.creative.ports.preparation_store import (
    ProductionReadyCreativePackage,
)
from ai_content.platform.artifacts.store import ArtifactStore
from ai_content.platform.llm_routing import normalize_persisted_agent_model_id

_PACKAGE_ADAPTER = TypeAdapter(ProductionReadyCreativePackage)


def package_artifact_ref(request_id: str) -> str:
    return f"marketing-creative-automation/{request_id}/production_ready_package.json"


def write_production_ready_package(
    store: ArtifactStore,
    package: ProductionReadyCreativePackage,
) -> str:
    reference = package_artifact_ref(package.request.request_id)
    payload = _PACKAGE_ADAPTER.dump_json(package, indent=2).decode()
    store.write_text(payload, *reference.split("/"))
    return reference


def read_production_ready_package(
    store: ArtifactStore, request_id: str
) -> ProductionReadyCreativePackage | None:
    reference = package_artifact_ref(request_id)
    payload = store.read_text(*reference.split("/"))
    if payload is None:
        return None
    return validate_production_ready_package(payload)


def validate_production_ready_package(
    payload: str | bytes,
) -> ProductionReadyCreativePackage:
    """Read current and known legacy package payloads without rewriting their artifacts."""

    raw_payload = json.loads(payload)
    request = raw_payload.get("request")
    if isinstance(request, dict):
        model = request.get("agent_model_id")
        if isinstance(model, str):
            normalized_model = normalize_persisted_agent_model_id(model)
            if normalized_model != model:
                raw_payload = {
                    **raw_payload,
                    "request": {**request, "agent_model_id": normalized_model},
                }
    return _PACKAGE_ADAPTER.validate_python(raw_payload)


def automation_state_artifact_ref(request_id: str) -> str:
    return f"marketing-creative-automation/{request_id}/state.json"


class FileMarketingCreativeAutomationStateRepository:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def reference(self, request_id: str) -> str:
        return automation_state_artifact_ref(request_id)

    def save(self, state: MarketingCreativeAutomationState) -> str:
        reference = self.reference(state.request_id)
        payload = TypeAdapter(MarketingCreativeAutomationState).dump_json(state, indent=2).decode()
        self._store.write_text(payload, *reference.split("/"))
        return reference

    def get(self, request_id: str) -> MarketingCreativeAutomationState | None:
        reference = automation_state_artifact_ref(request_id)
        payload = self._store.read_text(*reference.split("/"))
        if payload is None:
            return None
        return TypeAdapter(MarketingCreativeAutomationState).validate_json(payload)


__all__ = [
    "FileMarketingCreativeAutomationStateRepository",
    "automation_state_artifact_ref",
    "package_artifact_ref",
    "read_production_ready_package",
    "validate_production_ready_package",
    "write_production_ready_package",
]
