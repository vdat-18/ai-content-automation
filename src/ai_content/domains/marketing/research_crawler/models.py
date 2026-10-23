"""Typed state for public web research crawl jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResearchCrawlStatus = Literal["queued", "pending", "running", "retry_wait", "completed", "failed"]
ResearchMediaMode = Literal["images", "videos", "images_and_videos"]
ResearchReviewStatus = Literal["pending_review", "approved", "rejected"]
ResearchScreeningStatus = Literal["kept", "auto_filtered", "unavailable"]
ResearchCrawlPhase = Literal[
    "queued",
    "opening_browser",
    "navigating",
    "loading_results",
    "scrolling",
    "extracting",
    "saving",
    "capturing_media",
    "classifying",
    "completed",
    "failed",
]


class ResearchBrandContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brand_id: str
    version: str
    source_versions: tuple[str, ...]
    product_facts: tuple[str, ...]
    supporting_facts: tuple[str, ...] = ()


class ResearchMediaAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    media_id: str
    media_kind: Literal["image", "video"]
    source_url_fingerprint: str
    source_url: str
    status: Literal["available", "failed"]
    artifact_ref: str | None = None
    content_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    error_code: str | None = None


class ResearchClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "failed"]
    taxonomy_version: str
    model: str
    content_hash: str
    labels: dict[str, str] = Field(default_factory=dict)
    probabilities: dict[str, dict[str, float]] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    error_code: str | None = None


class ResearchReferenceProfile(BaseModel):
    """Semantic brief that lets Marketing and Creative understand a reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=1_000)
    relevance_to_project: str = Field(min_length=1, max_length=1_000)
    primary_subject: str = Field(default="", max_length=1_000)
    content_goal: str = Field(default="", max_length=1_000)
    reference_types: tuple[str, ...] = ()
    product_categories: tuple[str, ...] = ()
    visual_style: tuple[str, ...] = ()
    composition: tuple[str, ...] = ()
    setting: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()
    camera_motion: tuple[str, ...] = ()
    text_treatment: tuple[str, ...] = ()
    temporal_structure: tuple[str, ...] = ()
    audio: tuple[str, ...] = ()
    hook: str = Field(default="", max_length=1_000)
    message: str = Field(default="", max_length=1_000)
    creative_takeaways: tuple[str, ...] = ()
    do_not_copy: tuple[str, ...] = ()
    observed_facts: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    media_notes: tuple[str, ...] = ()
    applicability_constraints: tuple[str, ...] = ()


class ResearchScreening(BaseModel):
    """Provider-neutral usability decision plus a semantic reference brief."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "failed"]
    prompt_version: str
    model: str
    content_hash: str
    config_hash: str = ""
    context_version: str = ""
    usable: bool
    reason_code: str
    reason: str
    confidence: float = Field(ge=0, le=1)
    profile: ResearchReferenceProfile | None = None
    error_code: str | None = None
    attempt_count: int = Field(default=1, ge=1)
    last_attempted_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def read_legacy_decision(cls, value: Any) -> Any:
        if isinstance(value, dict) and "usable" not in value and "decision" in value:
            value = dict(value)
            value["usable"] = value.pop("decision") != "discard"
        return value


class ResearchCrawlProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: ResearchCrawlPhase = "queued"
    discovered_records: int = 0
    processed_records: int = 0
    source_records_discovered: int = 0
    media_candidates: int = 0
    duplicate_records: int = 0
    media_captured: int = 0
    media_analysis_completed: int = 0
    saved_records: int = 0
    new_records: int = 0
    updated_records: int = 0
    unchanged_records: int = 0
    failed_records: int = 0
    accepted_records: int = 0
    rejected_records: int = 0
    auto_filtered_records: int = 0
    analysis_unavailable_records: int = 0
    image_count: int = 0
    video_count: int = 0
    scroll_count: int = 0
    expected_records: int | None = None
    stop_reason: str | None = None
    navigation_step: int = 0
    navigation_action: str | None = None
    navigation_confidence: float | None = None
    page_status: str | None = None


class ResearchCrawlRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    record_type: str
    title: str | None = None
    text: str = ""
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: list[dict[str, str]] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)


class ResearchCrawlResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    final_url: str
    platform: str
    http_status: int
    content_type: str
    title: str | None = None
    description: str | None = None
    text: str = ""
    headings: dict[str, list[str]] = Field(default_factory=dict)
    metadata: list[dict[str, str]] = Field(default_factory=list)
    json_ld: list[Any] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    records: list[ResearchCrawlRecord] = Field(default_factory=list)
    records_complete: bool | None = None
    raw_artifact_ref: str
    raw_size_bytes: int


class ResearchCrawlJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    workspace_id: str
    brand_id: str
    project_id: str | None = None
    source_url: str
    media_mode: ResearchMediaMode = "images_and_videos"
    analysis_model_id: str | None = None
    crawl_fingerprint: str | None = None
    status: ResearchCrawlStatus
    command_id: str | None = None
    brand_context: ResearchBrandContext | None = None
    progress: ResearchCrawlProgress = Field(default_factory=ResearchCrawlProgress)
    result: ResearchCrawlResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StoredResearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_key: str
    workspace_id: str
    brand_id: str
    platform: str
    external_id: str
    record_type: str
    title: str | None = None
    text: str = ""
    source_url: str | None = None
    status: str | None = None
    advertiser: str | None = None
    destination_domain: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: list[dict[str, str]] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    media_assets: list[ResearchMediaAsset] = Field(default_factory=list)
    media_content_hash: str = ""
    classification: ResearchClassification | None = None
    screening_status: ResearchScreeningStatus = "unavailable"
    screening: ResearchScreening | None = None
    review_status: ResearchReviewStatus = "pending_review"
    reviewer_alias: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    content_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    latest_run_id: str
    version_count: int = 1


class ResearchRecordVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: str
    record_key: str
    job_id: str
    content_hash: str
    record: ResearchCrawlRecord
    observed_at: datetime


class ResearchRecordQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str | None = None
    brand_id: str | None = None
    project_id: str | None = None
    platform: str | None = None
    status: str | None = None
    review_status: ResearchReviewStatus | None = None
    screening_status: Literal["visible", "auto_filtered", "unavailable", "all"] = "visible"
    media_type: Literal["all", "image", "video", "mixed", "none"] = "all"
    media_status: Literal["all", "available", "failed", "source_only"] = "all"
    category: str | None = None
    query: str | None = None
    sort: Literal["last_seen_desc", "first_seen_desc", "title_asc"] = "last_seen_desc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=48, ge=1, le=100)


class ResearchRecordPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[StoredResearchRecord]
    total: int
    page: int
    page_size: int


class ResearchRecordUpsertSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    saved: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0


__all__ = [
    "ResearchBrandContext",
    "ResearchCrawlJob",
    "ResearchCrawlPhase",
    "ResearchCrawlProgress",
    "ResearchCrawlRecord",
    "ResearchCrawlResult",
    "ResearchCrawlStatus",
    "ResearchClassification",
    "ResearchMediaAsset",
    "ResearchRecordPage",
    "ResearchRecordQuery",
    "ResearchReferenceProfile",
    "ResearchReviewStatus",
    "ResearchScreening",
    "ResearchScreeningStatus",
    "ResearchRecordUpsertSummary",
    "ResearchRecordVersion",
    "StoredResearchRecord",
]
