"""Strict synthetic fixture schema for Email production."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_content.domains.marketing.email_health.domain.models import (
    EmailHealthClassification,
    EmailHealthRule,
    EmailHealthRuleSet,
    EmailHealthSubjectType,
    HealthObservation,
    HealthObservationName,
    HealthRuleOperator,
    HealthRuleStatus,
    HealthSeverity,
    ObservationStatus,
    ObservationValueType,
    RemediationAction,
)

from ..application.production import EmailProductionRequest
from ..domain.models import (
    ContextComponent,
    ContextEvidence,
    ContextStatus,
    EmailContextSnapshot,
    EmailPackage,
    EmailSection,
    EmailTrigger,
    ReviewOutcome,
    SemanticReview,
)


class ContextEvidenceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: ContextComponent
    status: ContextStatus
    evidence_refs: list[str] = Field(default_factory=list)
    observed_at: datetime
    valid_until: datetime | None = None
    detail: str | None = None


class ContextFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    version: str
    brand_id: str
    account_id: str
    timezone: str
    collection_ref: str
    product_refs: list[str] = Field(min_length=1)
    offer_ref: str | None = None
    audience_ref: str
    exclusion_ref: str
    approved_claim_refs: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(min_length=1)
    forbidden_phrases: list[str] = Field(default_factory=list)
    forbidden_punctuation: list[str] = Field(default_factory=list)
    cross_brand_terms: list[str] = Field(default_factory=list)
    components: list[ContextEvidenceFixture] = Field(min_length=1)
    version_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    captured_at: datetime

    def domain(self) -> EmailContextSnapshot:
        return EmailContextSnapshot(
            **self.model_dump(
                exclude={
                    "product_refs",
                    "approved_claim_refs",
                    "asset_refs",
                    "forbidden_phrases",
                    "forbidden_punctuation",
                    "cross_brand_terms",
                    "components",
                    "version_refs",
                    "evidence_refs",
                }
            ),
            product_refs=tuple(self.product_refs),
            approved_claim_refs=tuple(self.approved_claim_refs),
            asset_refs=tuple(self.asset_refs),
            forbidden_phrases=tuple(self.forbidden_phrases),
            forbidden_punctuation=tuple(self.forbidden_punctuation),
            cross_brand_terms=tuple(self.cross_brand_terms),
            components=tuple(
                ContextEvidence(
                    **item.model_dump(exclude={"evidence_refs"}),
                    evidence_refs=tuple(item.evidence_refs),
                )
                for item in self.components
            ),
            version_refs=tuple(self.version_refs),
            evidence_refs=tuple(self.evidence_refs),
        )


class SectionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str
    heading: str
    body: str
    cta_label: str | None = None
    destination_url: str | None = None
    product_refs: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    design_note: str


class PackageFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_name: str
    subject_variants: list[str] = Field(min_length=2)
    preview_text: str
    outline: list[str] = Field(min_length=1)
    sections: list[SectionFixture] = Field(min_length=1)
    offer_ref: str | None = None
    claim_refs: list[str] = Field(default_factory=list)
    audience_ref: str
    exclusion_ref: str
    send_at: datetime
    timezone: str

    def domain(self) -> EmailPackage:
        return EmailPackage(
            **self.model_dump(exclude={"subject_variants", "outline", "sections", "claim_refs"}),
            subject_variants=tuple(self.subject_variants),
            outline=tuple(self.outline),
            sections=tuple(
                EmailSection(
                    **item.model_dump(exclude={"product_refs", "asset_refs"}),
                    product_refs=tuple(item.product_refs),
                    asset_refs=tuple(item.asset_refs),
                )
                for item in self.sections
            ),
            claim_refs=tuple(self.claim_refs),
        )


class ReviewFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_version: str
    outcome: ReviewOutcome
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    def domain(self) -> SemanticReview:
        return SemanticReview(
            reviewer_version=self.reviewer_version,
            outcome=self.outcome,
            score=self.score,
            issues=tuple(self.issues),
            repair_instructions=tuple(self.repair_instructions),
            evidence_refs=tuple(self.evidence_refs),
        )


class ObservationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: HealthObservationName
    status: ObservationStatus
    value_type: ObservationValueType
    source_ref: str | None = None
    observed_at: datetime
    boolean_value: bool | None = None
    decimal_value: Decimal | None = None
    text_value: str | None = None
    reason: str | None = None

    def domain(self, account_id: str, source: str, integration_id: str | None) -> HealthObservation:
        return HealthObservation(
            **self.model_dump(exclude={"source_ref"}),
            account_id=account_id,
            source_system=source,
            integration_id=integration_id,
            source_ref=self.source_ref or "email-version-pending",
        )


class RuleFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    observation: HealthObservationName
    operator: HealthRuleOperator
    severity: HealthSeverity
    failure_classification: EmailHealthClassification
    recommendation: RemediationAction
    description: str
    expected_boolean: bool | None = None
    threshold_decimal: Decimal | None = None
    expected_text: str | None = None


class RuleSetFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_set_id: str
    version: str
    status: HealthRuleStatus
    effective_at: datetime
    source: str
    rules: list[RuleFixture] = Field(min_length=1)

    def domain(self) -> EmailHealthRuleSet:
        return EmailHealthRuleSet(
            rule_set_id=self.rule_set_id,
            version=self.version,
            status=self.status,
            effective_at=self.effective_at,
            source=self.source,
            rules=tuple(
                EmailHealthRule(
                    subject_type=EmailHealthSubjectType.CAMPAIGN,
                    **item.model_dump(),
                )
                for item in self.rules
            ),
        )


class PreflightFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_set_ref: str
    observed_at: datetime
    source_version: str
    source_system: str
    integration_id: str | None = None
    observations: list[ObservationFixture] = Field(min_length=1)


class EmailProductionCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_id: str
    source_run_id: str
    source: str
    brand_id: str
    account_id: str
    objective: str
    scheduled_at: datetime
    trigger_evidence_refs: list[str] = Field(min_length=1)
    context: ContextFixture
    prompt_version: str
    policy_version: str
    workflow_version: str
    generator_version: str
    max_revisions: int = Field(ge=0, le=5)
    packages: list[PackageFixture] = Field(min_length=1)
    reviews: list[ReviewFixture] = Field(min_length=1)
    preflight: PreflightFixture

    def request(self) -> EmailProductionRequest:
        trigger = EmailTrigger(
            trigger_id=self.trigger_id,
            source_run_id=self.source_run_id,
            source=self.source,
            brand_id=self.brand_id,
            account_id=self.account_id,
            objective=self.objective,
            scheduled_at=self.scheduled_at,
            evidence_refs=tuple(self.trigger_evidence_refs),
        )
        context = self.context.domain()
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return EmailProductionRequest(
            trigger=trigger,
            context=context,
            source_checksum_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            prompt_version=self.prompt_version,
            policy_version=self.policy_version,
            workflow_version=self.workflow_version,
            max_revisions=self.max_revisions,
        )


class EmailProductionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preflight_rule_sets: list[RuleSetFixture] = Field(min_length=1)
    cases: list[EmailProductionCaseFixture] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> EmailProductionFixture:
        source_ids = [item.source_run_id for item in self.cases]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Email production source_run_id values must be unique")
        rules = {item.rule_set_id for item in self.preflight_rule_sets}
        if any(item.preflight.rule_set_ref not in rules for item in self.cases):
            raise ValueError("Email production case references an unknown preflight rule set")
        return self


def load_email_production_fixture(path: Path) -> EmailProductionFixture:
    return EmailProductionFixture.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["EmailProductionFixture", "load_email_production_fixture"]
