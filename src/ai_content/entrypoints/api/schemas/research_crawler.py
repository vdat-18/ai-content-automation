"""API schemas for workspace-neutral public research crawls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_content.domains.marketing.research_crawler.models import ResearchMediaMode
from ai_content.platform.llm_routing import DEFAULT_RESEARCH_MODEL


class ResearchCrawlCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=120)
    brand_id: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=120)
    source_url: str = Field(min_length=8, max_length=4096)
    media_mode: ResearchMediaMode = "images_and_videos"
    analysis_model_id: str = DEFAULT_RESEARCH_MODEL

    @field_validator("workspace_id", "brand_id", "project_id")
    @classmethod
    def strip_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("scope values must not be blank")
        return normalized

    @field_validator("analysis_model_id")
    @classmethod
    def approved_analysis_model(cls, value: str) -> str:
        from ai_content.platform.llm_routing import require_approved_agent_model

        return require_approved_agent_model(value)


class ResearchCrawlRecordResponse(BaseModel):
    record_id: str
    record_type: str
    title: str | None
    text: str
    source_url: str | None
    metadata: dict[str, Any]
    links: list[dict[str, str]]
    image_urls: list[str]
    video_urls: list[str]


class ResearchCrawlResultResponse(BaseModel):
    final_url: str
    platform: str
    http_status: int
    content_type: str
    title: str | None
    description: str | None
    text: str
    headings: dict[str, list[str]]
    metadata: list[dict[str, str]]
    json_ld: list[Any]
    links: list[dict[str, str]]
    image_urls: list[str]
    video_urls: list[str]
    records: list[ResearchCrawlRecordResponse]
    records_complete: bool | None
    raw_artifact_ref: str
    raw_size_bytes: int


class ResearchReferenceProfileResponse(BaseModel):
    summary: str
    relevance_to_project: str
    primary_subject: str
    content_goal: str
    reference_types: tuple[str, ...]
    product_categories: tuple[str, ...]
    visual_style: tuple[str, ...]
    composition: tuple[str, ...]
    setting: tuple[str, ...]
    colors: tuple[str, ...]
    camera_motion: tuple[str, ...]
    text_treatment: tuple[str, ...]
    temporal_structure: tuple[str, ...]
    audio: tuple[str, ...]
    hook: str
    message: str
    creative_takeaways: tuple[str, ...]
    do_not_copy: tuple[str, ...]
    observed_facts: tuple[str, ...]
    inferences: tuple[str, ...]
    media_notes: tuple[str, ...]
    applicability_constraints: tuple[str, ...]


class ResearchScreeningResponse(BaseModel):
    status: Literal["completed", "failed"]
    prompt_version: str
    model: str
    content_hash: str
    config_hash: str
    context_version: str
    usable: bool
    reason_code: str
    reason: str
    confidence: float
    profile: ResearchReferenceProfileResponse | None
    error_code: str | None
    attempt_count: int
    last_attempted_at: datetime | None


class ResearchCrawlProgressResponse(BaseModel):
    phase: str
    discovered_records: int
    processed_records: int
    source_records_discovered: int
    media_candidates: int
    media_captured: int
    media_analysis_completed: int
    saved_records: int
    new_records: int
    updated_records: int
    unchanged_records: int
    failed_records: int
    accepted_records: int
    rejected_records: int
    auto_filtered_records: int
    analysis_unavailable_records: int
    image_count: int
    video_count: int
    scroll_count: int
    expected_records: int | None
    stop_reason: str | None
    navigation_step: int
    navigation_action: str | None
    navigation_confidence: float | None


class ResearchBrandContextResponse(BaseModel):
    brand_id: str
    version: str
    source_versions: tuple[str, ...]
    product_facts: tuple[str, ...]
    supporting_facts: tuple[str, ...]


class ResearchCrawlJobResponse(BaseModel):
    job_id: str
    workspace_id: str
    brand_id: str
    project_id: str | None
    source_url: str
    media_mode: ResearchMediaMode
    analysis_model_id: str | None = None
    status: str
    command_id: str | None
    brand_context: ResearchBrandContextResponse | None
    progress: ResearchCrawlProgressResponse
    result: ResearchCrawlResultResponse | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ResearchCrawlListResponse(BaseModel):
    items: list[ResearchCrawlJobResponse]
    total: int


class ResearchMediaAssetResponse(BaseModel):
    media_id: str
    media_kind: str
    source_url_fingerprint: str
    source_url: str
    status: str
    artifact_ref: str | None
    content_type: str | None
    sha256: str | None
    size_bytes: int | None
    error_code: str | None


class ResearchClassificationResponse(BaseModel):
    status: str
    taxonomy_version: str
    model: str
    content_hash: str
    labels: dict[str, str]
    probabilities: dict[str, dict[str, float]]
    confidence: dict[str, float]
    error_code: str | None


class StoredResearchRecordResponse(BaseModel):
    record_key: str
    workspace_id: str
    brand_id: str
    platform: str
    external_id: str
    record_type: str
    title: str | None
    text: str
    source_url: str | None
    status: str | None
    advertiser: str | None
    destination_domain: str | None
    metadata: dict[str, Any]
    links: list[dict[str, str]]
    image_urls: list[str]
    video_urls: list[str]
    media_assets: list[ResearchMediaAssetResponse]
    media_content_hash: str
    classification: ResearchClassificationResponse | None
    screening_status: Literal["kept", "auto_filtered", "unavailable"]
    screening: ResearchScreeningResponse | None
    review_status: Literal["pending_review", "approved", "rejected"]
    reviewer_alias: str | None
    reviewed_at: datetime | None
    review_reason: str | None
    content_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    latest_run_id: str
    version_count: int


class ResearchRecordReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "review_later"]
    reviewer_alias: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=1_000)

    @field_validator("reviewer_alias", "reason")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_reviewer_for_decision(self) -> ResearchRecordReviewRequest:
        if self.decision in {"approve", "reject"} and self.reviewer_alias is None:
            raise ValueError("reviewer_alias is required to approve or reject research")
        return self


class ResearchRecordBulkReviewRequest(ResearchRecordReviewRequest):
    record_keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("record_keys")
    @classmethod
    def normalize_record_keys(cls, values: list[str]) -> list[str]:
        keys = [value.strip() for value in values]
        if any(not value for value in keys):
            raise ValueError("record_keys must not contain blank values")
        if len(set(keys)) != len(keys):
            raise ValueError("record_keys must not contain duplicates")
        return keys


class ResearchRecordBulkReviewResponse(BaseModel):
    items: list[StoredResearchRecordResponse]
    total: int


class ResearchRecordDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("record_keys")
    @classmethod
    def normalize_record_keys(cls, values: list[str]) -> list[str]:
        keys = [value.strip() for value in values]
        if any(not value for value in keys):
            raise ValueError("record_keys must not contain blank values")
        if len(set(keys)) != len(keys):
            raise ValueError("record_keys must not contain duplicates")
        return keys


class ResearchRecordDeleteResponse(BaseModel):
    deleted: int


class ResearchKeywordSuggestionResponse(BaseModel):
    keyword: str


class ResearchKeywordSuggestionListResponse(BaseModel):
    brand_id: str
    items: list[ResearchKeywordSuggestionResponse]


class ResearchRecordVersionResponse(BaseModel):
    version_id: str
    record_key: str
    job_id: str
    content_hash: str
    record: ResearchCrawlRecordResponse
    observed_at: datetime


class ResearchRecordPageResponse(BaseModel):
    items: list[StoredResearchRecordResponse]
    total: int
    page: int
    page_size: int


class ResearchRecordDetailResponse(BaseModel):
    record: StoredResearchRecordResponse
    versions: list[ResearchRecordVersionResponse]


__all__ = [
    "ResearchBrandContextResponse",
    "ResearchCrawlCreateRequest",
    "ResearchCrawlJobResponse",
    "ResearchCrawlListResponse",
    "ResearchCrawlProgressResponse",
    "ResearchCrawlRecordResponse",
    "ResearchCrawlResultResponse",
    "ResearchKeywordSuggestionListResponse",
    "ResearchKeywordSuggestionResponse",
    "ResearchRecordBulkReviewRequest",
    "ResearchRecordBulkReviewResponse",
    "ResearchRecordDetailResponse",
    "ResearchRecordDeleteRequest",
    "ResearchRecordDeleteResponse",
    "ResearchRecordPageResponse",
    "ResearchReferenceProfileResponse",
    "ResearchRecordReviewRequest",
    "ResearchScreeningResponse",
    "ResearchRecordVersionResponse",
    "StoredResearchRecordResponse",
]
