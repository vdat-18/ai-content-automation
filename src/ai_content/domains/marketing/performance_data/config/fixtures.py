"""Strict configuration for the offline GMC ingestion pilot."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import GmcIngestionSpec


class GmcFixture(BaseModel):
    """Paths and versioned rules for one sanitized local feed."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str
    brand_id: str
    store_id: str
    source_file: Path
    catalog_file: Path
    schema_version: str
    mapping_version: str
    required_columns: list[str] = Field(min_length=1)
    allowed_availability: list[str] = Field(
        default_factory=lambda: ["in_stock", "out_of_stock", "preorder", "backorder"]
    )
    chunk_size: int = Field(default=1000, ge=1, le=100_000)

    def specification(self) -> GmcIngestionSpec:
        return GmcIngestionSpec(
            source_run_id=self.source_run_id,
            brand_id=self.brand_id,
            store_id=self.store_id,
            schema_version=self.schema_version,
            mapping_version=self.mapping_version,
            required_columns=tuple(self.required_columns),
            allowed_availability=tuple(self.allowed_availability),
            chunk_size=self.chunk_size,
            source_ref=str(self.source_file),
        )


def load_gmc_fixture(path: Path) -> GmcFixture:
    """Read and validate a fixture, resolving paths relative to its directory."""
    fixture = GmcFixture.model_validate_json(path.read_text(encoding="utf-8"))
    base = path.resolve().parent
    return fixture.model_copy(
        update={
            "source_file": (base / fixture.source_file).resolve()
            if not fixture.source_file.is_absolute()
            else fixture.source_file,
            "catalog_file": (base / fixture.catalog_file).resolve()
            if not fixture.catalog_file.is_absolute()
            else fixture.catalog_file,
        }
    )


__all__ = ["GmcFixture", "load_gmc_fixture"]
