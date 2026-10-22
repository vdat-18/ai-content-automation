"""Versioned backup manifest contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DatabaseTableInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObjectInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: int = Field(default=1, ge=1)
    backup_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    source_revision: str | None = None
    source_dirty: bool | None = None
    alembic_revision: str | None = None
    execution_backend: str | None = None
    dbos_application_version: str | None = None
    database_dump_file: str = "postgres.dump"
    database_dump_size_bytes: int = Field(ge=0)
    database_dump_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_tables: tuple[DatabaseTableInventory, ...]
    bucket: str = Field(min_length=1)
    objects: tuple[ObjectInventory, ...]
    object_count: int = Field(ge=0)
    object_bytes: int = Field(ge=0)


__all__ = ["BackupManifest", "DatabaseTableInventory", "ObjectInventory"]
