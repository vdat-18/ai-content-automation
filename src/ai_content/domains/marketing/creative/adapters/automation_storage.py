"""Storage boundary for selected-SKU Creative automation packages and state."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from ai_content.domains.marketing.creative.adapters.automation_artifacts import (
    FileMarketingCreativeAutomationStateRepository,
    automation_state_artifact_ref,
    package_artifact_ref,
    read_production_ready_package,
    validate_production_ready_package,
    write_production_ready_package,
)
from ai_content.domains.marketing.creative.adapters.automation_state_postgres import (
    PostgresMarketingCreativeAutomationStateRepository,
)
from ai_content.domains.marketing.creative.ports.automation_workflow import (
    MarketingCreativeAutomationState,
)
from ai_content.domains.marketing.creative.ports.preparation_store import (
    ProductionReadyCreativePackage,
)
from ai_content.platform.artifacts import (
    ArtifactKind,
    ArtifactService,
    ArtifactStatus,
    ArtifactStore,
)


class MarketingCreativeAutomationStorage(Protocol):
    """Persist the request state and the immutable package that it pins."""

    shared_across_processes: bool

    async def write_package(self, package: ProductionReadyCreativePackage) -> str: ...

    async def read_package(
        self,
        request_id: str,
        package_ref: str | None = None,
    ) -> ProductionReadyCreativePackage | None: ...

    async def get(self, request_id: str) -> MarketingCreativeAutomationState | None: ...

    async def package_ref(self, request_id: str) -> str | None: ...

    async def create(
        self,
        state: MarketingCreativeAutomationState,
    ) -> MarketingCreativeAutomationState: ...

    async def save(
        self, state: MarketingCreativeAutomationState
    ) -> MarketingCreativeAutomationState: ...

    def workflow_ref(self, request_id: str) -> str: ...


class FileMarketingCreativeAutomationStorage:
    """Filesystem compatibility storage for SQLite development and unit tests."""

    shared_across_processes = False

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store
        self._states = FileMarketingCreativeAutomationStateRepository(store)

    async def write_package(self, package: ProductionReadyCreativePackage) -> str:
        return write_production_ready_package(self._store, package)

    async def read_package(
        self,
        request_id: str,
        package_ref: str | None = None,
    ) -> ProductionReadyCreativePackage | None:
        del package_ref
        return read_production_ready_package(self._store, request_id)

    async def get(self, request_id: str) -> MarketingCreativeAutomationState | None:
        return self._states.get(request_id)

    async def package_ref(self, request_id: str) -> str | None:
        reference = package_artifact_ref(request_id)
        return reference if self._store.exists(*reference.split("/")) else None

    async def create(
        self,
        state: MarketingCreativeAutomationState,
    ) -> MarketingCreativeAutomationState:
        existing = self._states.get(state.request_id)
        if existing is not None:
            return existing
        self._states.save(state)
        return state

    async def save(
        self, state: MarketingCreativeAutomationState
    ) -> MarketingCreativeAutomationState:
        self._states.save(state)
        return state

    def workflow_ref(self, request_id: str) -> str:
        return automation_state_artifact_ref(request_id)


class ObjectStorageMarketingCreativeAutomationStorage:
    """PostgreSQL state plus catalogued, immutable object-storage packages."""

    shared_across_processes = True

    def __init__(
        self,
        states: PostgresMarketingCreativeAutomationStateRepository,
        artifacts: ArtifactService,
        scratch_root: Path,
    ) -> None:
        self._states = states
        self._artifacts = artifacts
        self._scratch_root = scratch_root

    async def write_package(self, package: ProductionReadyCreativePackage) -> str:
        self._scratch_root.mkdir(parents=True, exist_ok=True)
        payload = TypeAdapter(ProductionReadyCreativePackage).dump_json(package, indent=2)
        with tempfile.NamedTemporaryFile(
            dir=self._scratch_root,
            prefix="creative-package-",
            suffix=".json",
            delete=False,
        ) as pending:
            pending.write(payload)
            temporary = Path(pending.name)
        try:
            record = await self._artifacts.publish_file(
                temporary,
                package_artifact_ref(package.request.request_id),
                kind=ArtifactKind.PROJECTION,
                owner_type="marketing_creative_automation",
                owner_id=package.request.request_id,
                brand_scope=package.request.brand,
            )
        finally:
            temporary.unlink(missing_ok=True)
        return f"artifact:{record.artifact_id}"

    async def read_package(
        self,
        request_id: str,
        package_ref: str | None = None,
    ) -> ProductionReadyCreativePackage | None:
        record = None
        if package_ref is not None and package_ref.startswith("artifact:"):
            record = await self._artifacts.catalog.get(package_ref.removeprefix("artifact:"))
            if record is None:
                return None
        else:
            record = await self._artifacts.catalog.latest_available(
                package_artifact_ref(request_id)
            )
        if record is None:
            return None
        if record.status != ArtifactStatus.AVAILABLE:
            raise ValueError("Creative package artifact is not available")
        with self._artifacts.storage.open(record.object_key) as download:
            payload = download.stream.read()
        if (
            len(payload) != record.size_bytes
            or hashlib.sha256(payload).hexdigest() != record.sha256
        ):
            raise ValueError("Creative package artifact failed integrity verification")
        package = validate_production_ready_package(payload)
        if package.request.request_id != request_id:
            raise ValueError("Creative package artifact does not match the requested workflow")
        return package

    async def get(self, request_id: str) -> MarketingCreativeAutomationState | None:
        return await self._states.get(request_id)

    async def package_ref(self, request_id: str) -> str | None:
        state = await self._states.get(request_id)
        if state is not None and state.package_ref.startswith("artifact:"):
            return state.package_ref
        record = await self._artifacts.catalog.latest_available(package_artifact_ref(request_id))
        return f"artifact:{record.artifact_id}" if record is not None else None

    async def create(
        self,
        state: MarketingCreativeAutomationState,
    ) -> MarketingCreativeAutomationState:
        return await self._states.create(state)

    async def save(
        self, state: MarketingCreativeAutomationState
    ) -> MarketingCreativeAutomationState:
        return await self._states.save(state)

    def workflow_ref(self, request_id: str) -> str:
        return f"database:marketing-creative-automation-states/{request_id}"


__all__ = [
    "FileMarketingCreativeAutomationStorage",
    "MarketingCreativeAutomationStorage",
    "ObjectStorageMarketingCreativeAutomationStorage",
]
