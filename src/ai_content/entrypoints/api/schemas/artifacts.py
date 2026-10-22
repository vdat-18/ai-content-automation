"""Artifact catalog API schemas."""

from datetime import datetime

from pydantic import BaseModel


class ArtifactResponse(BaseModel):
    artifact_id: str
    kind: str
    status: str
    source_path: str
    sha256: str
    size_bytes: int
    content_type: str
    retention_class: str
    owner_type: str
    owner_id: str
    brand_scope: str | None
    created_at: datetime
    content_url: str


__all__ = ["ArtifactResponse"]
