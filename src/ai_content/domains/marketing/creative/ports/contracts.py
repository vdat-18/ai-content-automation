"""Input contracts for Creative subdomain.

These define the exact data required for each operation.
All fields are properly typed, no dict[str, Any] for important data.

Contract chain (plan section 4-5):
CreativeWorkItemInput -> SkuInput -> ContextPackage -> IdeaPackage
    -> StaticCreativeInput -> RevisionRequest
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from ..domain.reviews import RepairAction
from ..domain.value_objects import GenerationBudget


class ProofType(StrEnum):
    CLAIM = "claim"
    TESTIMONIAL = "testimonial"
    STATISTIC = "statistic"
    CERTIFICATION = "certification"


class ProvenanceSource(StrEnum):
    AI_PROPOSED = "ai_proposed"
    TEAM_PROVIDED = "team_provided"
    SOURCE_OF_TRUTH = "source_of_truth"


class ProductionRoute(StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTOMATED = "automated"


class SkuProductionTier(StrEnum):
    HERO = "hero"
    WINNER = "winner"
    SCALE = "scale"
    LONG_TAIL = "long_tail"
    OVERFLOW = "overflow"


class CreativeAutomationExecutionMode(StrEnum):
    BRIEF_ONLY = "brief_only"
    GENERATE_ONCE = "generate_once"


class CreativeReferenceSelectionMode(StrEnum):
    NONE = "none"
    AGENT = "agent"  # Persisted-package compatibility; create API no longer accepts it.
    HUMAN = "human"


class ProductSelectionScope(StrEnum):
    PRODUCT_FAMILY = "product_family"
    VARIANT = "variant"


class ProductMediaSelectionMode(StrEnum):
    AGENT = "agent"
    MANUAL = "manual"
    FEATURED = "featured"


class CreativeSetStrategy(StrEnum):
    SINGLE = "single"
    MULTI_ANGLE = "multi_angle"
    LAYOUT_VARIATIONS = "layout_variations"
    BACKGROUND_VARIATIONS = "background_variations"
    COPY_VARIATIONS = "copy_variations"
    CAROUSEL = "carousel"


@dataclass(frozen=True)
class CreativeReferenceCandidate:
    """Immutable human-authorized image available to Creative planning."""

    reference_id: str
    record_key: str
    media_id: str
    artifact_ref: str
    checksum_sha256: str
    description: str
    platform: str
    source_url: str | None = None
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.reference_id,
            self.record_key,
            self.media_id,
            self.artifact_ref,
            self.description,
            self.platform,
        )
        if not all(value.strip() for value in required):
            raise ValueError("Creative reference identity and description are required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("Creative reference checksum must be SHA-256")


@dataclass(frozen=True)
class CreativeReferenceAssignment:
    """Exact visual references pinned by Marketing to one requested output."""

    output_key: str
    reference_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"(?:image|video):[1-9][0-9]*", self.output_key):
            raise ValueError("Creative reference assignment has an invalid output key")
        if not self.reference_ids:
            raise ValueError("Creative reference assignment requires at least one reference")
        if any(not item.strip() for item in self.reference_ids):
            raise ValueError("Creative reference assignment IDs cannot be empty")
        if len(self.reference_ids) != len(set(self.reference_ids)):
            raise ValueError("Creative reference assignment IDs must be unique")


SUPPORTED_MARKET_COUNTRIES = frozenset({"US", "GB", "DE", "FR", "ES", "IT", "NL"})


@dataclass(frozen=True)
class AssetReference:
    url: str
    provenance: ProvenanceSource
    license_info: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ProductAsset:
    url: str
    asset_type: str
    provenance: ProvenanceSource


@dataclass(frozen=True)
class ProofReference:
    proof_type: ProofType
    text: str
    source_url: str | None = None
    verified: bool = False


@dataclass(frozen=True)
class OutputSpec:
    width: int
    height: int
    file_format: str
    aspect_ratio: str | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive")


@dataclass(frozen=True)
class CreativeOutputProfile:
    profile_id: str
    media_kind: Literal["image", "video"]
    aspect_ratio: str
    file_format: str
    count: int = 1
    image_size: str | None = None

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("Creative output profile ID is required")
        if self.aspect_ratio not in {"1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("Unsupported Creative aspect ratio")
        allowed_formats = {"image": {"png", "jpeg", "webp"}, "video": {"mp4"}}
        if self.file_format not in allowed_formats[self.media_kind]:
            raise ValueError("Unsupported Creative output format")
        if self.count < 1:
            raise ValueError("Creative output profile count must be positive")


@dataclass(frozen=True)
class CreativeOutputSelection:
    """Marketing-facing output scope for one independently executable SKU job."""

    image_count: int = 3
    video_count: int = 1
    video_duration_seconds: int | None = None
    video_duration_min_seconds: int = 15
    video_duration_max_seconds: int = 60
    video_scene_duration_max_seconds: int = 15
    include_background_music: bool = False
    aspect_ratio: str = "9:16"
    profiles: tuple[CreativeOutputProfile, ...] = ()

    @property
    def image_output_count(self) -> int:
        if self.profiles:
            return sum(item.count for item in self.profiles if item.media_kind == "image")
        return self.image_count

    @property
    def video_output_count(self) -> int:
        if self.profiles:
            return sum(item.count for item in self.profiles if item.media_kind == "video")
        return self.video_count

    @property
    def requires_video_plan(self) -> bool:
        return self.video_output_count > 0

    @property
    def output_profiles(self) -> tuple[CreativeOutputProfile, ...]:
        if self.profiles:
            return self.profiles
        profiles: list[CreativeOutputProfile] = []
        if self.image_count:
            profiles.append(
                CreativeOutputProfile(
                    profile_id=f"image-{self.aspect_ratio}",
                    media_kind="image",
                    aspect_ratio=self.aspect_ratio,
                    file_format="png",
                    count=self.image_count,
                )
            )
        if self.video_count:
            profiles.append(
                CreativeOutputProfile(
                    profile_id=f"video-{self.aspect_ratio}",
                    media_kind="video",
                    aspect_ratio=self.aspect_ratio,
                    file_format="mp4",
                    count=self.video_count,
                )
            )
        return tuple(profiles)

    def __post_init__(self) -> None:
        if self.image_count < 0:
            raise ValueError("image_count cannot be negative")
        if self.video_count < 0:
            raise ValueError("video_count cannot be negative")
        if self.video_duration_min_seconds < 1:
            raise ValueError("Video duration minimum must be positive")
        if self.video_duration_max_seconds < self.video_duration_min_seconds:
            raise ValueError("Video duration range is invalid")
        if self.video_scene_duration_max_seconds < 1:
            raise ValueError("Video scene duration maximum must be positive")
        if (
            self.video_output_count > 0
            and self.video_duration_seconds is not None
            and not (
                self.video_duration_min_seconds
                <= self.video_duration_seconds
                <= self.video_duration_max_seconds
            )
        ):
            raise ValueError("Selected video duration must be within the configured range")
        if self.profiles:
            profile_ids = [item.profile_id for item in self.profiles]
            if len(profile_ids) != len(set(profile_ids)):
                raise ValueError("Creative output profile IDs must be unique")
        if self.image_output_count == 0 and self.video_output_count == 0:
            raise ValueError("At least one image or video output is required")
        if self.aspect_ratio not in {"1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("Unsupported Creative aspect ratio")


@dataclass(frozen=True)
class ProductFamilyRef:
    source_id: str
    product_id: str
    family_key: str
    store_id: str | None = None
    mapping_version: str = "shopify-product@1"

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.source_id, self.product_id, self.family_key)):
            raise ValueError("Product family source, product ID and family key are required")


@dataclass(frozen=True)
class ProductOptionContext:
    option_id: str
    name: str
    position: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class ProductVariantContext:
    variant_id: str
    sku: str | None
    title: str
    position: int
    selected_options: tuple[tuple[str, str], ...]
    price: Decimal | None
    compare_at_price: Decimal | None
    media_ids: tuple[str, ...]
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.variant_id.strip() or not self.title.strip():
            raise ValueError("Product variant ID and title are required")


@dataclass(frozen=True)
class ProductMediaContext:
    media_id: str
    url: str
    position: int
    variant_ids: tuple[str, ...]
    alt: str | None = None
    width: int | None = None
    height: int | None = None
    artifact_ref: str | None = None
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.media_id.strip() or not self.url.strip():
            raise ValueError("Product media ID and URL are required")
        if self.position < 1:
            raise ValueError("Product media position must be positive")
        if (self.artifact_ref is None) != (self.checksum_sha256 is None):
            raise ValueError("Frozen product media requires both artifact reference and checksum")
        if self.checksum_sha256 is not None and len(self.checksum_sha256) != 64:
            raise ValueError("Product media checksum must be SHA-256")


@dataclass(frozen=True)
class ProductFact:
    namespace: str
    key: str
    value_type: str
    raw_value: str
    canonical_value: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.namespace, self.key, self.value_type)):
            raise ValueError("Product fact namespace, key and type are required")


@dataclass(frozen=True)
class ProductFamilyContext:
    ref: ProductFamilyRef
    handle: str
    title: str
    description_html: str | None
    vendor: str | None
    product_type: str | None
    status: str | None
    tags: tuple[str, ...]
    options: tuple[ProductOptionContext, ...]
    variants: tuple[ProductVariantContext, ...]
    media: tuple[ProductMediaContext, ...]
    facts: tuple[ProductFact, ...]
    published_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.handle.strip() or not self.title.strip():
            raise ValueError("Product family handle and title are required")
        if not self.variants:
            raise ValueError("Product family requires at least one variant")
        variant_ids = {item.variant_id for item in self.variants}
        if len(variant_ids) != len(self.variants):
            raise ValueError("Product family variant IDs must be unique")
        media_ids = {item.media_id for item in self.media}
        if len(media_ids) != len(self.media):
            raise ValueError("Product family media IDs must be unique")
        if any(not set(item.variant_ids).issubset(variant_ids) for item in self.media):
            raise ValueError("Product media references an unknown variant")


@dataclass(frozen=True)
class MarketingCreativeAutomationRequest:
    """A Lead Marketing request to produce Creative for one selected SKU."""

    request_id: str
    brand: str
    sku_id: str
    market: str
    platform: str
    objective: str
    output: CreativeOutputSelection
    sku_tier: SkuProductionTier
    requested_by: str
    execution_mode: CreativeAutomationExecutionMode = CreativeAutomationExecutionMode.GENERATE_ONCE
    agent_model_id: str | None = None
    agent_reasoning_effort: str | None = None
    image_provider_id: str | None = None
    image_model_id: str | None = None
    image_resolution: str | None = None
    image_quality: str | None = None
    image_background: str | None = None
    image_moderation: str | None = None
    image_output_compression: int | None = None
    image_input_fidelity: str | None = None
    image_generation_mode: str | None = None
    video_model_id: str | None = None
    video_resolution: str | None = None
    video_generate_audio: bool | None = None
    notes: str | None = None
    high_brand_risk: bool = False
    automation_override: bool = False
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    product_family: ProductFamilyRef | None = None
    selection_scope: ProductSelectionScope = ProductSelectionScope.PRODUCT_FAMILY
    selected_variant_id: str | None = None
    product_media_selection_mode: ProductMediaSelectionMode = ProductMediaSelectionMode.AGENT
    selected_product_media_ids: tuple[str, ...] = ()
    reference_candidates: tuple[CreativeReferenceCandidate, ...] = ()
    reference_assignments: tuple[CreativeReferenceAssignment, ...] = ()
    reference_selection_mode: CreativeReferenceSelectionMode = CreativeReferenceSelectionMode.NONE
    creative_set_strategy: CreativeSetStrategy = CreativeSetStrategy.SINGLE
    include_text: bool = False
    headline: str | None = None
    subtext: str | None = None
    cta_text: str | None = None
    brand_instructions: str | None = None
    include_logo: bool = False
    logo_asset_id: str | None = None
    logo_artifact_ref: str | None = None
    logo_checksum_sha256: str | None = None
    human_persona: str | None = None
    human_angle: str | None = None
    human_hooks: tuple[str, ...] = ()
    human_offer: str | None = None
    human_claims: tuple[str, ...] = ()
    campaign_theme: str | None = None

    def __post_init__(self) -> None:
        required = {
            "request_id": self.request_id,
            "brand": self.brand,
            "sku_id": self.sku_id,
            "market": self.market,
            "platform": self.platform,
            "objective": self.objective,
            "requested_by": self.requested_by,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                f"Required automation request fields are missing: {', '.join(missing)}"
            )
        if self.market not in SUPPORTED_MARKET_COUNTRIES:
            raise ValueError("Creative automation market must be a supported country code")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must include timezone information")
        if self.video_model_id is not None and not self.video_model_id.strip():
            raise ValueError("Video model ID cannot be empty")
        if self.agent_model_id is not None:
            from ai_content.platform.llm_routing import (
                require_approved_agent_model,
                require_supported_agent_reasoning_level,
            )

            require_approved_agent_model(self.agent_model_id)
            if self.agent_reasoning_effort is not None:
                require_supported_agent_reasoning_level(
                    self.agent_model_id, self.agent_reasoning_effort
                )
        if self.image_provider_id is not None and not self.image_provider_id.strip():
            raise ValueError("Image provider ID cannot be empty")
        if self.image_model_id is not None and not self.image_model_id.strip():
            raise ValueError("Image model ID cannot be empty")
        if self.image_resolution is not None and not self.image_resolution.strip():
            raise ValueError("Image resolution cannot be empty")
        if self.image_quality is not None and not self.image_quality.strip():
            raise ValueError("Image quality cannot be empty")
        if self.image_input_fidelity not in {None, "low", "high"}:
            raise ValueError("Image input fidelity is unsupported")
        if self.image_generation_mode not in {None, "single_image_edit", "multi_image_edit"}:
            raise ValueError("Image generation mode is unsupported")
        if self.video_resolution is not None and not self.video_resolution.strip():
            raise ValueError("Video resolution cannot be empty")
        if (
            self.selection_scope == ProductSelectionScope.VARIANT
            and not (self.selected_variant_id or "").strip()
        ):
            raise ValueError("Variant selection requires selected_variant_id")
        if self.selection_scope == ProductSelectionScope.PRODUCT_FAMILY and (
            self.selected_variant_id is not None
        ):
            raise ValueError("Product family selection cannot pin a variant")
        if len(self.selected_product_media_ids) != len(set(self.selected_product_media_ids)):
            raise ValueError("Selected product media IDs must be unique")
        output_keys = [item.output_key for item in self.reference_assignments]
        if len(output_keys) != len(set(output_keys)):
            raise ValueError("Creative reference assignment output keys must be unique")
        expected_output_keys = {
            *(f"image:{index}" for index in range(1, self.output.image_output_count + 1)),
            *(f"video:{index}" for index in range(1, self.output.video_output_count + 1)),
        }
        if not set(output_keys).issubset(expected_output_keys):
            raise ValueError("Creative reference assignment targets an unknown output")
        candidate_ids = {item.reference_id for item in self.reference_candidates}
        assigned_ids = {
            reference_id
            for assignment in self.reference_assignments
            for reference_id in assignment.reference_ids
        }
        if not assigned_ids.issubset(candidate_ids):
            raise ValueError("Creative reference assignment references an unavailable candidate")
        if self.reference_selection_mode == CreativeReferenceSelectionMode.AGENT and (
            self.reference_assignments
        ):
            raise ValueError("Agent-selected Research references cannot be pre-assigned")
        if self.reference_selection_mode == CreativeReferenceSelectionMode.HUMAN and (
            not self.reference_assignments
        ):
            raise ValueError("Human-selected Research references require exact assignments")
        if (self.logo_artifact_ref is None) != (self.logo_checksum_sha256 is None):
            raise ValueError("Logo artifact requires both reference and checksum")
        if self.logo_checksum_sha256 is not None and len(self.logo_checksum_sha256) != 64:
            raise ValueError("Logo checksum must be SHA-256")
        if not self.include_text and any((self.headline, self.subtext, self.cta_text)):
            raise ValueError("Approved copy requires image text to be enabled")
        if self.include_logo and self.logo_artifact_ref is None:
            raise ValueError("Enabled image logo requires a ready logo asset")
        if not self.include_logo and self.logo_artifact_ref is not None:
            raise ValueError("Logo asset requires image logo to be enabled")


@dataclass(frozen=True)
class ProductionRoutingDecision:
    route: ProductionRoute
    reasons: tuple[str, ...]
    requires_override: bool = False

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("Production routing requires at least one reason")


@dataclass(frozen=True)
class PromptVersion:
    prompt_id: str
    version: str

    def __str__(self) -> str:
        return f"{self.prompt_id}@{self.version}"


@dataclass(frozen=True)
class RubricVersion:
    rubric_id: str
    version: str
    is_draft: bool = True

    def __str__(self) -> str:
        return f"{self.rubric_id}@{self.version}"


@dataclass(frozen=True)
class PolicyVersion:
    policy_id: str
    version: str

    def __str__(self) -> str:
        return f"{self.policy_id}@{self.version}"


@dataclass(frozen=True)
class RuleVersion:
    rule_id: str
    version: str

    def __str__(self) -> str:
        return f"{self.rule_id}@{self.version}"


@dataclass(frozen=True)
class WorkflowVersionRef:
    workflow_id: str
    version: str

    def __str__(self) -> str:
        return f"{self.workflow_id}@{self.version}"


@dataclass(frozen=True)
class MarketingScope:
    brand: str
    market: str

    def __post_init__(self) -> None:
        if not self.brand:
            raise ValueError("Brand is required")
        if not self.market:
            raise ValueError("Market is required")


@dataclass(frozen=True)
class ProductMetadata:
    image_refs: tuple[str, ...]
    price: Decimal | None = None
    currency: str | None = None
    offer: str | None = None
    differentiators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.currency is not None and len(self.currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")


@dataclass(frozen=True)
class CreativeConstraints:
    format_spec: OutputSpec
    brand_guideline_ref: str | None = None
    banned_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomerContext:
    pain_points: tuple[str, ...] = ()
    promises: tuple[str, ...] = ()
    target_stage: str | None = None


@dataclass(frozen=True)
class HistoricalCreativeContext:
    tested_angles: tuple[str, ...] = ()
    performance_notes: str | None = None


@dataclass(frozen=True)
class LeadFeedbackContext:
    common_issues: tuple[str, ...] = ()
    recent_rejections: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentContext:
    source_decision_ref: str
    category: str
    priority: int
    hypothesis: str
    experiment: str
    success_signal: str
    evidence_refs: tuple[str, ...]
    uncertainty: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 5:
            raise ValueError("Experiment priority must be between 1 and 5")
        if not all(
            value.strip()
            for value in (
                self.source_decision_ref,
                self.category,
                self.hypothesis,
                self.experiment,
                self.success_signal,
            )
        ):
            raise ValueError("Experiment context fields are required")
        if not self.evidence_refs:
            raise ValueError("Experiment context requires evidence")


@dataclass(frozen=True)
class SkuInput:
    """Per-SKU input required before idea creation (plan section 4.2)."""

    sku_id: str
    sku_name: str
    product_metadata: ProductMetadata
    creative_constraints: CreativeConstraints
    customer_context: CustomerContext
    historical_creative_context: HistoricalCreativeContext
    lead_feedback_context: LeadFeedbackContext | None = None
    product_family: ProductFamilyContext | None = None

    def __post_init__(self) -> None:
        if not self.sku_id:
            raise ValueError("SKU ID is required")
        if not self.sku_name:
            raise ValueError("SKU name is required")


@dataclass(frozen=True)
class EvidenceRef:
    """Reference to a source read during context gathering."""

    source_id: str
    data_version: str
    retrieved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.data_version:
            raise ValueError("data_version is required")


@dataclass(frozen=True)
class ContextPackage:
    """Output of context gathering for one SKU (plan section 6.2)."""

    context_id: str
    source_run_id: str
    sku_id: str
    brand: str
    evidence: tuple[EvidenceRef, ...]
    historical: HistoricalCreativeContext
    brand_guideline_ref: str | None = None
    risk_flags: tuple[str, ...] = ()
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.context_id:
            raise ValueError("context_id is required")
        if not self.source_run_id:
            raise ValueError("source_run_id is required")
        if not self.sku_id:
            raise ValueError("sku_id is required")
        if not self.brand:
            raise ValueError("brand is required")
        if len(self.evidence) == 0:
            raise ValueError("At least one evidence ref is required")


@dataclass(frozen=True)
class FidelityCheck:
    check_id: str
    passed: bool


@dataclass(frozen=True)
class IdeaPackage:
    """First-class creative idea output (plan section 5.1)."""

    idea_id: str
    brand: str
    sku_id: str
    objective: str
    market: str
    persona: str
    angle: str
    hook: str
    concept: str
    evidence_refs: tuple[str, ...] = ()
    fidelity_checks: tuple[FidelityCheck, ...] = ()
    risk_flags: tuple[str, ...] = ()
    confidence: Decimal = Decimal("50")
    duration_plan: GenerationBudget | None = None

    def __post_init__(self) -> None:
        if not self.idea_id:
            raise ValueError("idea_id is required")
        if not self.persona:
            raise ValueError("persona is required")
        if not self.angle:
            raise ValueError("angle is required")
        if not self.hook:
            raise ValueError("hook is required")
        if not self.concept:
            raise ValueError("concept is required")
        if self.confidence < 0 or self.confidence > 100:
            raise ValueError("confidence must be between 0 and 100")


@dataclass(frozen=True)
class RevisionRequest:
    """Structured revision input derived from a failed QA check.

    The generator must respect immutable_constraints and may only change
    what allowed_changes permits (plan section 18, gap 2).
    """

    previous_version_ref: str
    issues: tuple[str, ...] = ()
    feedback: str | None = None
    immutable_constraints: tuple[str, ...] = ()
    allowed_changes: tuple[str, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    failed_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.previous_version_ref:
            raise ValueError("previous_version_ref is required")
        if not self.issues and not self.feedback:
            raise ValueError("A revision requires issues or feedback")


@dataclass(frozen=True)
class NormalizedRegion:
    """Canvas region expressed on a provider-independent 0-1000 grid."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("Composition regions must have positive bounds")
        if self.x + self.width > 1000 or self.y + self.height > 1000:
            raise ValueError("Composition regions must fit within the normalized canvas")


@dataclass(frozen=True)
class TextPlacement:
    region: NormalizedRegion
    alignment: Literal["left", "center", "right"]
    text_color: str
    background_color: str | None = None

    def __post_init__(self) -> None:
        color_pattern = r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?"
        if re.fullmatch(color_pattern, self.text_color) is None:
            raise ValueError("Text color must be a six- or eight-digit hex color")
        if self.background_color and re.fullmatch(color_pattern, self.background_color) is None:
            raise ValueError("Text background must be a six- or eight-digit hex color")


@dataclass(frozen=True)
class ProductPreservationSpec:
    """Select one exact source image for deterministic product preservation."""

    source_index: int
    segmentation_prompt: str

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("Product source index must be non-negative")
        if not self.segmentation_prompt.strip():
            raise ValueError("Product segmentation prompt is required")


@dataclass(frozen=True)
class StaticCompositionSpec:
    """Versioned plan used by the image backend and deterministic renderer."""

    composition_id: str
    version: str
    visual_prompt: str
    product_region: NormalizedRegion
    heading: TextPlacement
    evidence_refs: tuple[str, ...]
    rationale: str
    subtext: TextPlacement | None = None
    logo_region: NormalizedRegion | None = None
    product_preservation: ProductPreservationSpec | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.composition_id, self.version, self.visual_prompt, self.rationale)
        ):
            raise ValueError("Composition identity, prompt and rationale are required")
        if not self.evidence_refs:
            raise ValueError("Composition requires evidence references")


@dataclass(frozen=True)
class StaticVariationPlan:
    """Explicit creative direction for one member of a Static Creative Set."""

    variation_key: str
    heading: str
    visual_direction: str
    subtext: str | None = None
    awareness_stage: str | None = None
    angle: str | None = None
    offer: str | None = None
    production_level: str | None = None
    evidence_refs: tuple[str, ...] = ()
    composition: StaticCompositionSpec | None = None

    def __post_init__(self) -> None:
        if not self.variation_key.strip():
            raise ValueError("Variation key is required")
        if not self.heading.strip():
            raise ValueError("Variation heading is required")
        if not self.visual_direction.strip():
            raise ValueError("Variation visual direction is required")


@dataclass(frozen=True)
class StaticCreativeInput:
    """Typed input contract for static creative generation.

    This is the complete input for generating one static creative version.
    Derived from an IdeaPackage plus SKU data; heading/visual_direction
    come from the selected idea, not from a human prompt.
    """

    brand: str
    sku: str
    objective: str
    idea_id: str
    heading: str
    visual_direction: str
    product_assets: tuple[ProductAsset, ...]
    output_spec: OutputSpec
    prompt_version: PromptVersion
    rubric_version: RubricVersion
    policy_version: PolicyVersion
    subtext: str | None = None
    reference_assets: tuple[AssetReference, ...] = field(default_factory=tuple)
    proof_references: tuple[ProofReference, ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "unknown"
    brand_guideline_ref: str | None = None
    banned_claims: tuple[str, ...] = ()
    creative_set_id: str | None = None
    variation_id: str | None = None
    variation_key: str | None = None
    variation_evidence_refs: tuple[str, ...] = ()
    awareness_stage: str | None = None
    angle: str | None = None
    offer: str | None = None
    production_level: str | None = None
    logo_asset: AssetReference | None = None
    composition: StaticCompositionSpec | None = None
    variation_plans: tuple[StaticVariationPlan, ...] = ()

    def __post_init__(self) -> None:
        if not self.brand:
            raise ValueError("Brand is required")
        if not self.sku:
            raise ValueError("SKU is required")
        if not self.idea_id:
            raise ValueError("idea_id is required")
        if not self.heading:
            raise ValueError("Heading is required")
        if not self.visual_direction:
            raise ValueError("Visual direction is required")
        if len(self.product_assets) == 0:
            raise ValueError("At least one product asset is required")


@dataclass(frozen=True)
class CreativeWorkItemInput:
    """Job-level input contract for one marketing work item (plan section 4.1).

    source_run_id is the idempotency key: the same trigger must not create
    two jobs.
    """

    source_run_id: str
    marketing_scope: MarketingScope
    objective: str
    channel: str
    time_window: str
    target_sku_set: tuple[SkuInput, ...]
    rubric_version: RubricVersion
    rule_version: RuleVersion
    prompt_version: PromptVersion
    policy_version: PolicyVersion
    workflow_version: WorkflowVersionRef
    persona_override: str | None = None
    creative_direction_override: str | None = None
    campaign_notes: str | None = None
    manual_priority_weight: Decimal | None = None
    experiment_context: ExperimentContext | None = None
    variation_count: int = 1
    variation_plans: tuple[StaticVariationPlan, ...] = ()
    requested_image_count: int = 1
    requested_video_count: int = 0
    created_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.source_run_id:
            raise ValueError("source_run_id is required")
        if not self.objective:
            raise ValueError("objective is required")
        if not self.channel:
            raise ValueError("channel is required")
        if not self.time_window:
            raise ValueError("time_window is required")
        if len(self.target_sku_set) == 0:
            raise ValueError("At least one SKU is required")
        if self.variation_count < 1:
            raise ValueError("variation_count must be at least 1")
        if self.requested_image_count < 0 or self.requested_video_count < 0:
            raise ValueError("Requested media counts cannot be negative")
        if self.variation_plans and len(self.variation_plans) != self.variation_count:
            raise ValueError("variation_plans must match variation_count")
        keys = [plan.variation_key for plan in self.variation_plans]
        if len(keys) != len(set(keys)):
            raise ValueError("variation_plans must use unique variation keys")


__all__ = [
    "ProofType",
    "ProvenanceSource",
    "ProductionRoute",
    "SkuProductionTier",
    "CreativeAutomationExecutionMode",
    "CreativeReferenceSelectionMode",
    "CreativeSetStrategy",
    "ProductSelectionScope",
    "ProductMediaSelectionMode",
    "SUPPORTED_MARKET_COUNTRIES",
    "AssetReference",
    "ProductAsset",
    "ProofReference",
    "OutputSpec",
    "CreativeOutputProfile",
    "CreativeOutputSelection",
    "MarketingCreativeAutomationRequest",
    "ProductFamilyRef",
    "ProductOptionContext",
    "ProductVariantContext",
    "ProductMediaContext",
    "ProductFact",
    "ProductFamilyContext",
    "ProductionRoutingDecision",
    "PromptVersion",
    "RubricVersion",
    "PolicyVersion",
    "RuleVersion",
    "WorkflowVersionRef",
    "MarketingScope",
    "ProductMetadata",
    "CreativeConstraints",
    "CustomerContext",
    "HistoricalCreativeContext",
    "LeadFeedbackContext",
    "ExperimentContext",
    "SkuInput",
    "EvidenceRef",
    "ContextPackage",
    "FidelityCheck",
    "IdeaPackage",
    "RevisionRequest",
    "NormalizedRegion",
    "TextPlacement",
    "ProductPreservationSpec",
    "StaticCompositionSpec",
    "StaticVariationPlan",
    "StaticCreativeInput",
    "CreativeWorkItemInput",
]
