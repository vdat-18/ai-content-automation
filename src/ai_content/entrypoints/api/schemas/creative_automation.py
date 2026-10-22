"""API contracts for Lead Marketing Creative automation requests."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketingCreativeOutputProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=80)
    media_kind: Literal["image", "video"]
    aspect_ratio: Literal["1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"]
    file_format: Literal["png", "jpeg", "webp", "mp4"]
    count: int = Field(default=1, ge=1)
    image_size: str | None = None

    @model_validator(mode="after")
    def compatible_format(self) -> "MarketingCreativeOutputProfileRequest":
        allowed = {"image": {"png", "jpeg", "webp"}, "video": {"mp4"}}
        if self.file_format not in allowed[self.media_kind]:
            raise ValueError("Output format is incompatible with the media kind")
        return self


class MarketingCreativeProductSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    family_key: str = Field(min_length=1)
    selection_scope: Literal["product_family", "variant"] = "product_family"
    variant_id: str | None = None
    media_selection_mode: Literal["agent", "manual"] = "agent"
    selected_media_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_manual_selection(cls, value):
        if isinstance(value, dict) and "media_selection_mode" not in value:
            value = dict(value)
            value["media_selection_mode"] = (
                "manual" if value.get("selected_media_ids") else "agent"
            )
        return value

    @field_validator("selected_media_ids")
    @classmethod
    def unique_media(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Selected product media IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Selected product media IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def valid_scope(self) -> "MarketingCreativeProductSelectionRequest":
        if self.selection_scope == "variant" and not (self.variant_id or "").strip():
            raise ValueError("Variant selection requires variant_id")
        if self.selection_scope == "product_family" and self.variant_id is not None:
            raise ValueError("Product family selection cannot include variant_id")
        if self.media_selection_mode == "manual" and not self.selected_media_ids:
            raise ValueError("Manual product media selection requires at least one image")
        if self.media_selection_mode != "manual" and self.selected_media_ids:
            raise ValueError("Only manual product media selection accepts selected media IDs")
        return self


class MarketingCreativeReferenceAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_key: str = Field(pattern=r"^(?:image|video):[1-9][0-9]*$")
    reference_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("reference_ids")
    @classmethod
    def unique_references(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Assigned reference IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Assigned reference IDs must be unique")
        return normalized


class MarketingCreativeVariantReferenceAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    reference_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("source_id", "product_id", "variant_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Variant reference identity cannot be empty")
        return normalized

    @field_validator("reference_ids")
    @classmethod
    def unique_references(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Assigned reference IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Assigned reference IDs must be unique")
        return normalized


class MarketingCreativeAutomationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_selections: list[MarketingCreativeProductSelectionRequest] = Field(default_factory=list)
    sku_ids: list[str] = Field(default_factory=list)
    brand: str = Field(min_length=1)
    market: Literal["US"] = "US"
    platform: str = Field(default="meta", min_length=1)
    objective: str = Field(default="conversion", min_length=1)
    agent_model_id: str | None = Field(default=None, min_length=1)
    agent_reasoning_effort: Literal["auto", "minimal", "low", "medium", "high"] = "auto"
    image_count: int = Field(default=1, ge=0)
    video_count: int = Field(default=0, ge=0)
    image_provider_id: str | None = Field(default=None, min_length=1)
    image_model_id: str | None = Field(default=None, min_length=1)
    image_resolution: Literal["1k", "1.5k", "2k"] | None = None
    image_quality: Literal["auto", "low", "medium", "high", "xhigh", "max"] | None = None
    image_background: Literal["auto", "opaque", "transparent"] | None = None
    image_moderation: Literal["auto", "low"] | None = None
    image_output_compression: int | None = Field(default=None, ge=0, le=100)
    image_input_fidelity: Literal["low", "high"] | None = None
    video_model_id: str | None = Field(default=None, min_length=1)
    video_resolution: Literal["480p", "720p", "1080p"] | None = None
    video_duration_seconds: int | None = Field(default=None, ge=1, le=30)
    video_generate_audio: bool | None = None
    aspect_ratio: str = Field(default="9:16")
    execution_mode: Literal["brief_only", "generate_once"] = "generate_once"
    sku_tier: str = Field(default="overflow")
    requested_by: str = Field(min_length=1)
    notes: str | None = None
    include_text: bool = False
    headline: str | None = Field(default=None, max_length=120)
    subtext: str | None = Field(default=None, max_length=240)
    cta_text: str | None = Field(default=None, max_length=48)
    brand_instructions: str | None = Field(default=None, max_length=1000)
    human_persona: str | None = Field(default=None, max_length=240)
    human_angle: str | None = Field(default=None, max_length=240)
    human_hooks: list[str] = Field(default_factory=list, max_length=3)
    human_offer: str | None = Field(default=None, max_length=240)
    human_claims: list[str] = Field(default_factory=list, max_length=10)
    include_logo: bool = False
    logo_asset_id: str | None = Field(default=None, min_length=1)
    use_research_references: bool = False
    reference_selection_mode: Literal["none", "human"] = "none"
    selected_reference_ids: list[str] = Field(default_factory=list, max_length=160)
    output_reference_assignments: list[MarketingCreativeReferenceAssignmentRequest] = Field(
        default_factory=list,
        max_length=20,
    )
    variant_reference_assignments: list[
        MarketingCreativeVariantReferenceAssignmentRequest
    ] = Field(default_factory=list, max_length=160)
    creative_set_strategy: Literal[
        "single",
        "multi_angle",
        "layout_variations",
        "background_variations",
        "copy_variations",
        "carousel",
    ] = "single"
    high_brand_risk: bool = False
    automation_override: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    output_profiles: list[MarketingCreativeOutputProfileRequest] = Field(default_factory=list)

    @field_validator("sku_ids")
    @classmethod
    def normalize_skus(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("SKU IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("SKU IDs must be unique within one request")
        return normalized

    @field_validator("selected_reference_ids")
    @classmethod
    def unique_references(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Selected reference IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Selected reference IDs must be unique")
        return normalized

    @field_validator("human_hooks", "human_claims")
    @classmethod
    def normalize_human_marketing_values(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Human marketing inputs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Human marketing inputs must be unique")
        return normalized

    @field_validator("aspect_ratio")
    @classmethod
    def supported_aspect_ratio(cls, value: str) -> str:
        if value not in {"1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("Unsupported Creative aspect ratio")
        return value

    @field_validator("sku_tier")
    @classmethod
    def supported_sku_tier(cls, value: str) -> str:
        if value not in {"hero", "winner", "scale", "long_tail", "overflow"}:
            raise ValueError("Unsupported SKU production tier")
        return value

    @field_validator("agent_model_id")
    @classmethod
    def approved_agent_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from ai_content.platform.llm_routing import require_approved_agent_model

        return require_approved_agent_model(value)

    @model_validator(mode="after")
    def valid_output_scope(self) -> "MarketingCreativeAutomationCreateRequest":
        from ai_content.platform.llm_routing import (
            DEFAULT_AGENT_MODEL,
            require_supported_agent_reasoning_level,
        )

        require_supported_agent_reasoning_level(
            self.agent_model_id or DEFAULT_AGENT_MODEL, self.agent_reasoning_effort
        )
        if not self.product_selections and not self.sku_ids:
            raise ValueError("At least one Product Family selection is required")
        if self.product_selections and self.sku_ids:
            raise ValueError("Use Product Family selections or legacy SKU IDs, not both")
        identities = [
            (item.source_id, item.product_id, item.selection_scope, item.variant_id)
            for item in self.product_selections
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Product Family selections must be unique")
        image_total = self.image_count
        video_total = self.video_count
        if self.output_profiles:
            profile_ids = [item.profile_id for item in self.output_profiles]
            if len(profile_ids) != len(set(profile_ids)):
                raise ValueError("Output profile IDs must be unique")
            image_total = sum(
                item.count for item in self.output_profiles if item.media_kind == "image"
            )
            video_total = sum(
                item.count for item in self.output_profiles if item.media_kind == "video"
            )
        if image_total == 0 and video_total == 0:
            raise ValueError("At least one image or video output is required")
        if image_total == 0 and (self.include_text or self.include_logo):
            raise ValueError("Image text and logo require at least one image output")
        assignment_keys = [item.output_key for item in self.output_reference_assignments]
        if len(assignment_keys) != len(set(assignment_keys)):
            raise ValueError("Reference assignment output keys must be unique")
        expected_output_keys = {
            *(f"image:{index}" for index in range(1, image_total + 1)),
            *(f"video:{index}" for index in range(1, video_total + 1)),
        }
        if not set(assignment_keys).issubset(expected_output_keys):
            raise ValueError("Reference assignment targets an unknown output")
        assigned_reference_ids = {
            reference_id
            for assignment in self.output_reference_assignments
            for reference_id in assignment.reference_ids
        }
        variant_assignment_keys = [
            (item.source_id, item.product_id, item.variant_id)
            for item in self.variant_reference_assignments
        ]
        if len(variant_assignment_keys) != len(set(variant_assignment_keys)):
            raise ValueError("Variant reference assignments must be unique")
        variant_reference_ids = {
            reference_id
            for assignment in self.variant_reference_assignments
            for reference_id in assignment.reference_ids
        }
        selected_reference_ids = set(self.selected_reference_ids)
        if self.output_reference_assignments and self.variant_reference_assignments:
            raise ValueError("Use output or Variant reference assignments, not both")
        expected_selected_ids = (
            variant_reference_ids
            if self.variant_reference_assignments
            else assigned_reference_ids
        )
        if (
            self.variant_reference_assignments or self.output_reference_assignments
        ) and selected_reference_ids != expected_selected_ids:
            raise ValueError("Selected reference IDs must match the configured reference assignments")
        if self.reference_selection_mode == "none" and self.use_research_references:
            self.reference_selection_mode = "human"
        self.use_research_references = self.reference_selection_mode != "none"
        if self.reference_selection_mode == "none" and (
            selected_reference_ids
            or self.output_reference_assignments
            or self.variant_reference_assignments
        ):
            raise ValueError("Disabled Research references cannot include a selection")
        if (
            self.reference_selection_mode == "human"
            and self.product_selections
            and not self.variant_reference_assignments
        ):
            raise ValueError(
                "Product selections require an explicit reference decision for every Variant"
            )
        if (
            self.reference_selection_mode == "human"
            and not self.product_selections
            and not selected_reference_ids
        ):
            raise ValueError(
                "Human-selected Research references require an explicit human selection"
            )
        for field_name in (
            "headline",
            "subtext",
            "cta_text",
            "notes",
            "brand_instructions",
            "human_persona",
            "human_angle",
            "human_offer",
        ):
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, value.strip() or None)
        if not self.include_text and any((self.headline, self.subtext, self.cta_text)):
            raise ValueError("Approved copy requires image text to be enabled")
        if self.include_logo and self.logo_asset_id is None:
            raise ValueError("Enable image logo only after uploading a logo")
        if not self.include_logo and self.logo_asset_id is not None:
            raise ValueError("Uploaded logo requires image logo to be enabled")
        return self


class MarketingCreativeAutomationIssueResponse(BaseModel):
    code: str
    detail: str
    component: str | None = None


class MarketingCreativeOutputProfileResponse(BaseModel):
    profile_id: str
    media_kind: Literal["image", "video"]
    aspect_ratio: str
    file_format: str
    count: int
    image_size: str | None = None


class MarketingCreativeMediaCapabilityResponse(BaseModel):
    status: str
    provider_id: str | None
    configuration_version: str | None
    fidelity_mode: Literal["generative", "exact_source_transform"] | None = None
    supported_aspect_ratios: list[str]
    supported_formats: list[str]
    max_reference_images: int | None
    supported_generation_durations_seconds: list[int]
    supports_native_voice: bool
    supports_native_music: bool
    max_final_duration_seconds: int | None = None
    models: list["MarketingCreativeVideoModelCapabilityResponse"] = Field(default_factory=list)
    image_models: list["MarketingCreativeImageModelCapabilityResponse"] = Field(
        default_factory=list
    )


class MarketingCreativeImageModelCapabilityResponse(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    fidelity_mode: Literal["generative", "exact_source_transform"]
    supported_modes: list[str]
    supported_aspect_ratios: list[str]
    supported_resolutions: list[str]
    supported_qualities: list[str]
    supported_formats: list[str]
    supported_image_sizes: list[str] = Field(default_factory=list)
    supported_backgrounds: list[str] = Field(default_factory=list)
    supported_moderation: list[str] = Field(default_factory=list)
    supported_input_fidelities: list[str] = Field(default_factory=list)
    supports_output_compression: bool = False
    max_reference_images: int
    supports_text_rendering: bool
    supports_logo_input: bool
    cost_per_output_by_setting: dict[str, str]
    input_image_cost: str


class MarketingCreativeVideoModelCapabilityResponse(BaseModel):
    model_id: str
    display_name: str
    fidelity_mode: Literal["generative", "exact_source_transform"]
    supported_aspect_ratios: list[str]
    supported_resolutions: list[str]
    supported_generation_durations_seconds: list[int]
    max_reference_images: int
    max_product_images: int
    reference_to_video_resolutions: list[str] = Field(default_factory=list)
    supports_native_voice: bool
    supports_native_music: bool


class MarketingCreativeAutomationCapabilitiesResponse(BaseModel):
    image: MarketingCreativeMediaCapabilityResponse
    video: MarketingCreativeMediaCapabilityResponse
    agent_models: list[str]
    default_agent_model_id: str
    agent_reasoning_levels: dict[str, list[str]]
    default_agent_reasoning_level: str


class MarketingCreativeAutomationItemResponse(BaseModel):
    request_id: str
    batch_id: str | None = None
    sku_id: str
    source_id: str | None = None
    product_id: str | None = None
    family_key: str | None = None
    selection_scope: Literal["product_family", "variant"] = "product_family"
    selected_variant_id: str | None = None
    product_media_selection_mode: Literal["agent", "manual", "featured"] = "agent"
    selected_product_media_ids: list[str] = Field(default_factory=list)
    route: str
    routing_reasons: list[str]
    status: str
    intake_run_id: str | None
    creative_job_id: str | None
    package_ref: str | None
    workflow_ref: str | None
    review_id: str | None
    asset_count: int
    ads_draft_id: str | None
    issues: list[MarketingCreativeAutomationIssueResponse]
    image_count: int
    video_count: int
    image_provider_id: str | None
    image_model_id: str | None
    image_resolution: str | None
    image_quality: str | None
    image_generation_mode: str | None
    video_duration_seconds: int | None
    video_model_id: str | None
    video_resolution: str | None
    video_generate_audio: bool | None
    video_duration_min_seconds: int
    video_duration_max_seconds: int
    video_scene_duration_max_seconds: int
    audio_selected_by_agent: bool
    execution_mode: Literal["brief_only", "generate_once"]
    provider_status: str
    output_profiles: list[MarketingCreativeOutputProfileResponse]


class MarketingCreativeAutomationBatchResponse(BaseModel):
    batch_id: str
    items: list[MarketingCreativeAutomationItemResponse]
    total: int


class MarketingCreativeAutomationListResponse(BaseModel):
    items: list[MarketingCreativeAutomationItemResponse]
    total: int


class MarketingCreativeAssetResponse(BaseModel):
    asset_version_id: str
    media_kind: Literal["image", "video"]
    artifact_ref: str
    artifact_web_url: str | None
    checksum_sha256: str
    content_type: str
    qa_summary: str
    revision_count: int
    provider_id: str
    cost: Decimal
    fidelity_mode: Literal["generative", "exact_source_transform"]
    product_source_checksum_sha256: str | None


class MarketingCreativeIntermediateArtifactResponse(BaseModel):
    artifact_ref: str
    artifact_web_url: str | None
    checksum_sha256: str
    content_type: str
    provider_id: str
    duration_seconds: int | None
    cost: Decimal
    fidelity_mode: Literal["generative", "exact_source_transform"]
    product_source_checksum_sha256: str | None


class MarketingCreativeProductionVersionResponse(BaseModel):
    asset_version_id: str
    parent_asset_version_id: str | None
    generation_request_id: str | None
    revision_feedback: str | None
    media_kind: Literal["image", "video"]
    variation_key: str
    success: bool
    outcome: str
    attempt_count: int
    total_cost: Decimal
    artifact_ref: str | None
    artifact_web_url: str | None
    checksum_sha256: str | None
    content_type: str | None
    provider_id: str | None
    actual_width: int | None
    actual_height: int | None
    actual_duration_seconds: int | None
    has_audio_stream: bool | None
    fidelity_mode: Literal["generative", "exact_source_transform"] | None
    product_source_checksum_sha256: str | None
    technical_check_summary: str | None
    intermediate_artifacts: list[MarketingCreativeIntermediateArtifactResponse]


class MarketingCreativeFinalReviewResponse(BaseModel):
    review_id: str
    direction_summary: str
    review_checklist: list[str]
    assets: list[MarketingCreativeAssetResponse]
    image_count: int
    video_count: int
    created_at: datetime


class MarketingCreativeManualTakeoverResponse(BaseModel):
    takeover_id: str
    requested_by: str
    reason: str
    requested_at: datetime


class MarketingCreativeReviewDecisionResponse(BaseModel):
    decision_id: str
    review_id: str
    decision: Literal["approve", "manual_takeover"]
    asset_version_ids: list[str]
    asset_checksums: list[str]
    reviewer_alias: str
    reason: str
    decided_at: datetime
    key_visual_asset_version_id: str | None


class MarketingCreativeAdsDraftResponse(BaseModel):
    draft_id: str
    destination_ref: str
    daily_budget: Decimal
    currency: str
    draft_fingerprint: str
    status: str
    asset_version_ids: list[str]
    asset_checksums: list[str]
    created_at: datetime


class MarketingCreativeAdsActivationResponse(BaseModel):
    platform: str
    account_id: str
    campaign_id: str
    ad_ids: list[str]
    activated_at: datetime


class MarketingCreativeAutomationEventResponse(BaseModel):
    event_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class MarketingCreativeAutomationLatencyStepResponse(BaseModel):
    step: str
    outcome: Literal["succeeded", "failed"]
    started_at: datetime
    completed_at: datetime
    duration_ms: float


class MarketingCreativeAutomationLatencyResponse(BaseModel):
    total_duration_ms: float | None
    total_outcome: Literal["succeeded", "failed"] | None
    is_final: bool
    steps: list[MarketingCreativeAutomationLatencyStepResponse]


class MarketingCreativeAutomationPlanResponse(BaseModel):
    plan_id: str
    readiness: str
    strategy_summary: str
    rationale: str
    evidence_refs: list[str]
    image_plans: list[dict[str, object]]
    video_plans: list[dict[str, object]]
    video_plan: dict[str, object] | None = None
    missing_context: list[str]
    uncertainties: list[str]
    memory_refs: list[str]
    model_profile: str
    prompt_version: str


class MarketingCreativeAutomationTraceResponse(BaseModel):
    request: dict[str, object]
    source_refs: list[str]
    memory_refs: list[str]
    knowledge_refs_by_stage: dict[str, list[str]]
    selected_idea: dict[str, object] | None
    prepared_brief: dict[str, object] | None
    strategy: dict[str, object] | None
    plan: MarketingCreativeAutomationPlanResponse | None
    events: list[MarketingCreativeAutomationEventResponse]
    input_tokens: int | None
    output_tokens: int | None
    total_cost: Decimal
    technical_checks: list[str]
    latency: MarketingCreativeAutomationLatencyResponse


class MarketingCreativeGenerationRequestResponse(BaseModel):
    generation_request_id: str
    requested_by: str
    reason: str
    requested_at: datetime
    target_asset_version_ids: list[str]
    knowledge_refs: list[str]


class MarketingCreativeAutomationDetailResponse(BaseModel):
    request_id: str
    package_id: str
    package_ref: str
    route: Literal["manual", "assisted", "automated"]
    status: str
    issues: list[MarketingCreativeAutomationIssueResponse] = Field(default_factory=list)
    final_review: MarketingCreativeFinalReviewResponse | None
    production_versions: list[MarketingCreativeProductionVersionResponse]
    review_decision: MarketingCreativeReviewDecisionResponse | None
    manual_takeover: MarketingCreativeManualTakeoverResponse | None
    ads_draft: MarketingCreativeAdsDraftResponse | None
    ads_approved: bool
    ads_provider_status: str
    ads_activation: MarketingCreativeAdsActivationResponse | None
    production_attempt_count: int
    generation_request_count: int
    generation_requests: list[MarketingCreativeGenerationRequestResponse]
    production_cost: Decimal
    production_error_code: str | None
    production_error_detail: str | None
    created_at: datetime
    updated_at: datetime
    trace: MarketingCreativeAutomationTraceResponse | None = None


class MarketingCreativeReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    asset_version_ids: list[str] = Field(min_length=1)
    asset_checksums: list[str] = Field(min_length=1)
    decision: Literal["approve", "manual_takeover"]
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    key_visual_asset_version_id: str | None = Field(default=None, min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_asset_set(self) -> "MarketingCreativeReviewDecisionRequest":
        if len(self.asset_version_ids) != len(self.asset_checksums):
            raise ValueError("Every Creative asset version requires a checksum")
        if any(len(value) != 64 for value in self.asset_checksums):
            raise ValueError("Creative asset checksums must be SHA-256")
        if len(self.asset_version_ids) != len(set(self.asset_version_ids)):
            raise ValueError("Creative asset versions must be unique")
        if (
            self.key_visual_asset_version_id is not None
            and self.key_visual_asset_version_id not in self.asset_version_ids
        ):
            raise ValueError("Key Visual must be one of the approved Creative assets")
        return self


class MarketingCreativeGenerateAgainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    target_asset_version_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("target_asset_version_ids")
    @classmethod
    def unique_targets(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Generate again targets cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Generate again targets must be unique")
        return normalized


class MarketingCreativeManualTakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MarketingCreativeAdsDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_ref: str = Field(min_length=1)
    daily_budget: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MarketingCreativeAdsApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    draft_fingerprint: str = Field(min_length=64, max_length=64)
    asset_version_ids: list[str] = Field(min_length=1)
    asset_checksums: list[str] = Field(min_length=1)
    reviewer_alias: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_asset_set(self) -> "MarketingCreativeAdsApprovalRequest":
        if len(self.asset_version_ids) != len(self.asset_checksums):
            raise ValueError("Every Ads asset version requires a checksum")
        if any(len(value) != 64 for value in self.asset_checksums):
            raise ValueError("Ads asset checksums must be SHA-256")
        return self


class MarketingCreativeAdsActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    draft_fingerprint: str = Field(min_length=64, max_length=64)
    asset_version_ids: list[str] = Field(min_length=1)
    asset_checksums: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_asset_set(self) -> "MarketingCreativeAdsActivationRequest":
        if len(self.asset_version_ids) != len(self.asset_checksums):
            raise ValueError("Every activation asset version requires a checksum")
        if any(len(value) != 64 for value in self.asset_checksums):
            raise ValueError("Activation asset checksums must be SHA-256")
        return self


__all__ = [
    "MarketingCreativeAdsActivationRequest",
    "MarketingCreativeAdsActivationResponse",
    "MarketingCreativeAdsApprovalRequest",
    "MarketingCreativeAdsDraftCreateRequest",
    "MarketingCreativeAdsDraftResponse",
    "MarketingCreativeAssetResponse",
    "MarketingCreativeAutomationBatchResponse",
    "MarketingCreativeAutomationCapabilitiesResponse",
    "MarketingCreativeMediaCapabilityResponse",
    "MarketingCreativeProductSelectionRequest",
    "MarketingCreativeAutomationCreateRequest",
    "MarketingCreativeAutomationDetailResponse",
    "MarketingCreativeAutomationIssueResponse",
    "MarketingCreativeAutomationLatencyResponse",
    "MarketingCreativeAutomationLatencyStepResponse",
    "MarketingCreativeIntermediateArtifactResponse",
    "MarketingCreativeAutomationItemResponse",
    "MarketingCreativeAutomationListResponse",
    "MarketingCreativeOutputProfileRequest",
    "MarketingCreativeOutputProfileResponse",
    "MarketingCreativeAutomationEventResponse",
    "MarketingCreativeAutomationPlanResponse",
    "MarketingCreativeAutomationTraceResponse",
    "MarketingCreativeFinalReviewResponse",
    "MarketingCreativeGenerateAgainRequest",
    "MarketingCreativeGenerationRequestResponse",
    "MarketingCreativeReviewDecisionRequest",
    "MarketingCreativeReviewDecisionResponse",
]
