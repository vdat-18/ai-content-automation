"""Strict configuration loader for allowlisted sandbox sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .domain.models import DataSourceDefinition, DataSourceProvider


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    provider: DataSourceProvider
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    base_url: HttpUrl
    resources: list[dict[str, Any]] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def definition(self) -> DataSourceDefinition:
        return DataSourceDefinition(
            source_id=self.source_id,
            provider=self.provider,
            name=self.name,
            category=self.category,
            purpose=self.purpose,
            base_url=str(self.base_url).rstrip("/"),
            resources=tuple(self.resources),
            metadata=self.metadata,
        )


class DataSourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceConfig]


def load_data_sources_config(path: Path | None) -> tuple[DataSourceDefinition, ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = DataSourcesConfig.model_validate(payload)
    definitions = tuple(item.definition() for item in config.sources)
    ids = [item.source_id for item in definitions]
    if len(ids) != len(set(ids)):
        raise ValueError("Data source IDs must be unique")
    return definitions


__all__ = ["DataSourcesConfig", "SourceConfig", "load_data_sources_config"]
