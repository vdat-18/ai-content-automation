"""External boundaries for bounded GMC ingestion."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from ..domain.models import (
    CatalogProduct,
    GmcIngestionRun,
    GmcIngestionSpec,
    ProcessedProductRow,
    SourceDescriptor,
)


class SourceReadError(Exception):
    """Expected source file inspection or streaming failure."""


class InputDriftError(Exception):
    """A replay key was reused with different immutable input."""


@dataclass(frozen=True)
class ArtifactWriteResult:
    normalized_ref: str
    rejected_ref: str
    normalized_checksum_sha256: str
    rejected_checksum_sha256: str


class IGmcSource(Protocol):
    def inspect(self, specification: GmcIngestionSpec) -> SourceDescriptor: ...

    def iter_rows(self, chunk_size: int) -> Iterator[tuple[int, dict[str, str]]]: ...


class IProductCatalogReference(Protocol):
    def find(self, gmc_product_id: str) -> tuple[CatalogProduct, ...]: ...


class IGmcOutputWriter(Protocol):
    def write(
        self, source_run_id: str, rows: Iterable[ProcessedProductRow]
    ) -> ArtifactWriteResult: ...


class IGmcRunRepository(Protocol):
    async def save(self, run: GmcIngestionRun) -> None: ...

    async def get(self, run_id: str) -> GmcIngestionRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> GmcIngestionRun | None: ...

    async def list(self) -> list[GmcIngestionRun]: ...
