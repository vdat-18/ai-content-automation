"""API schemas for read-only GMC ingestion runs."""

from pydantic import BaseModel


class GmcRunIssueResponse(BaseModel):
    code: str
    severity: str
    detail: str
    source_ref: str | None


class GmcRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    brand_id: str
    store_id: str
    status: str
    source_ref: str
    source_checksum_sha256: str
    source_size_bytes: int
    schema_version: str
    mapping_version: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    matched_rows: int
    gmc_only_rows: int
    conflicting_rows: int
    duplicate_rows: int
    normalized_artifact_ref: str | None
    rejected_artifact_ref: str | None
    normalized_checksum_sha256: str | None
    rejected_checksum_sha256: str | None
    created_at: str
    issues: list[GmcRunIssueResponse]


class GmcRunListResponse(BaseModel):
    items: list[GmcRunResponse]
    total: int
