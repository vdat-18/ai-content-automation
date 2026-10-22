"""Domain models for approved, scoped Creative knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from .scope import canonical_brand_id, canonical_niche_id


class KnowledgeType(StrEnum):
    FACT = "fact"
    HARD_RULE = "hard_rule"
    TEAM_DEFAULT = "team_default"
    PRACTICE = "practice"
    HYPOTHESIS = "hypothesis"
    LESSON = "lesson"
    QA_CHECK = "qa_check"
    DECISION = "decision"
    FEEDBACK = "feedback"


class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CONFLICT = "conflict"


class KnowledgeAuthority(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    LEAD = "lead"
    TEAM = "team"
    INDIVIDUAL = "individual"
    EXTERNAL = "external"


class KnowledgeStage(StrEnum):
    PERSONA = "persona"
    PREPARATION = "preparation"
    ORCHESTRATION = "orchestration"
    REVIEW = "review"
    REVISION = "revision"
    LEARNING = "learning"
    PERFORMANCE = "performance"


LEGACY_GENERATION_STAGES = (
    KnowledgeStage.PERSONA,
    KnowledgeStage.PREPARATION,
    KnowledgeStage.ORCHESTRATION,
)


@dataclass(frozen=True)
class KnowledgeScope:
    niche_id: str | None = None
    brand_id: str | None = None
    product_archetype: str | None = None
    product_family_id: str | None = None
    variant_id: str | None = None
    platform: str | None = None
    market: str | None = None
    asset_type: str | None = None
    task_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "brand_id", canonical_brand_id(self.brand_id))
        object.__setattr__(self, "niche_id", canonical_niche_id(self.niche_id))

    def specificity(self) -> int:
        return sum(value is not None for value in self.__dict__.values())

    def matches(self, query: KnowledgeScope) -> bool:
        return all(
            expected is None or expected == getattr(query, name)
            for name, expected in self.__dict__.items()
        )


@dataclass(frozen=True)
class CreativeKnowledge:
    knowledge_id: str
    version: int
    knowledge_type: KnowledgeType
    title: str
    content: str
    scope: KnowledgeScope
    status: KnowledgeStatus
    authority: KnowledgeAuthority
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    applies_to: tuple[KnowledgeStage, ...] = LEGACY_GENERATION_STAGES
    contributor: str | None = None
    non_conclusions: tuple[str, ...] = ()
    effective_from: datetime | None = None
    valid_until: datetime | None = None
    supersedes: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.knowledge_id.strip() or not self.title.strip() or not self.content.strip():
            raise ValueError("Knowledge identity, title and content are required")
        if self.version < 1:
            raise ValueError("Knowledge version must be positive")
        if not self.source_refs:
            raise ValueError("Knowledge requires at least one source reference")
        if not self.applies_to:
            raise ValueError("Knowledge requires at least one application stage")
        if len(self.applies_to) != len(set(self.applies_to)):
            raise ValueError("Knowledge application stages must be unique")
        for name in ("effective_from", "valid_until", "approved_at", "created_at"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must include timezone information")
        if (
            self.valid_until is not None
            and self.effective_from is not None
            and self.valid_until <= self.effective_from
        ):
            raise ValueError("valid_until must be later than effective_from")
        if self.status == KnowledgeStatus.APPROVED and not self.approved_by:
            raise ValueError("Approved knowledge requires an approver")

    @property
    def version_ref(self) -> str:
        return f"{self.knowledge_id}@{self.version}"

    def decide(self, status: KnowledgeStatus, reviewer: str) -> CreativeKnowledge:
        if status not in {KnowledgeStatus.APPROVED, KnowledgeStatus.REJECTED}:
            raise ValueError("A review decision must approve or reject knowledge")
        if self.status not in {
            KnowledgeStatus.DRAFT,
            KnowledgeStatus.PROPOSED,
            KnowledgeStatus.CONFLICT,
        }:
            raise ValueError("Only draft, proposed or conflicting knowledge can be reviewed")
        return replace(
            self,
            status=status,
            approved_by=reviewer if status == KnowledgeStatus.APPROVED else None,
            approved_at=datetime.now(UTC) if status == KnowledgeStatus.APPROVED else None,
        )

    def supersede(self) -> CreativeKnowledge:
        if self.status != KnowledgeStatus.APPROVED:
            raise ValueError("Only approved knowledge can be superseded")
        return replace(self, status=KnowledgeStatus.SUPERSEDED)

    def active_at(self, when: datetime) -> bool:
        return (
            self.status == KnowledgeStatus.APPROVED
            and (self.effective_from is None or self.effective_from <= when)
            and (self.valid_until is None or when < self.valid_until)
        )


@dataclass(frozen=True)
class AppliedKnowledgeBootstrap:
    bootstrap_id: str
    schema_version: str
    checksum: str
    item_count: int
    applied_by: str
    applied_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.bootstrap_id,
                self.schema_version,
                self.checksum,
                self.applied_by,
            )
        ):
            raise ValueError("Bootstrap identity, checksum and actor are required")
        if self.item_count < 1:
            raise ValueError("Bootstrap must contain at least one knowledge item")
        if self.applied_at.tzinfo is None or self.applied_at.utcoffset() is None:
            raise ValueError("applied_at must include timezone information")


AUTHORITY_RANK = {
    KnowledgeAuthority.OWNER: 6,
    KnowledgeAuthority.ADMIN: 5,
    KnowledgeAuthority.LEAD: 4,
    KnowledgeAuthority.TEAM: 3,
    KnowledgeAuthority.INDIVIDUAL: 2,
    KnowledgeAuthority.EXTERNAL: 1,
}

TYPE_RANK = {
    KnowledgeType.HARD_RULE: 8,
    KnowledgeType.FACT: 7,
    KnowledgeType.DECISION: 6,
    KnowledgeType.QA_CHECK: 5,
    KnowledgeType.LESSON: 4,
    KnowledgeType.TEAM_DEFAULT: 3,
    KnowledgeType.PRACTICE: 2,
    KnowledgeType.HYPOTHESIS: 1,
    KnowledgeType.FEEDBACK: 1,
}
