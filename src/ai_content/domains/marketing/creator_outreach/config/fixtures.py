"""Strict synthetic fixtures for Creator outreach."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_content.domains.marketing.creator_operations.config.fixtures import (
    CreatorEvaluationFixture,
)
from ai_content.domains.marketing.creator_operations.domain.models import CandidateDecision

from ..application.workflow import CreatorOutreachRequest
from ..domain.models import (
    CreatorContactTrigger,
    OutreachPlan,
    OutreachPolicy,
    OutreachReview,
    ReplyField,
    ReplyFieldStatus,
    ReplyOutcome,
    ReplyRecord,
    ReviewOutcome,
)


class CreatorSourceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation: CreatorEvaluationFixture
    decision: CandidateDecision = CandidateDecision.CONTACT
    reviewer_alias: str
    reason: str

    def prepared_evaluation(self) -> CreatorEvaluationFixture:
        payload = json.dumps(
            self.evaluation.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return self.evaluation.model_copy(
            update={"source_checksum_sha256": hashlib.sha256(payload).hexdigest()}
        )


class OutreachPolicyFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    channel: str
    followup_interval_hours: int = Field(ge=1)
    max_followups: int = Field(ge=0)
    allowed_request_fields: list[str]
    forbidden_terms: list[str] = Field(default_factory=list)

    def domain(self) -> OutreachPolicy:
        return OutreachPolicy(
            **self.model_dump(exclude={"allowed_request_fields", "forbidden_terms"}),
            allowed_request_fields=tuple(self.allowed_request_fields),
            forbidden_terms=tuple(self.forbidden_terms),
        )


class OutreachPlanFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    initial_message: str
    followup_messages: list[str]
    requested_fields: list[str]
    personalization_evidence_refs: list[str]

    def domain(self) -> OutreachPlan:
        return OutreachPlan(
            **self.model_dump(
                exclude={
                    "followup_messages",
                    "requested_fields",
                    "personalization_evidence_refs",
                }
            ),
            followup_messages=tuple(self.followup_messages),
            requested_fields=tuple(self.requested_fields),
            personalization_evidence_refs=tuple(self.personalization_evidence_refs),
        )


class OutreachReviewFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_version: str
    outcome: ReviewOutcome
    issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    def domain(self) -> OutreachReview:
        return OutreachReview(
            **self.model_dump(exclude={"issues", "repair_instructions", "evidence_refs"}),
            issues=tuple(self.issues),
            repair_instructions=tuple(self.repair_instructions),
            evidence_refs=tuple(self.evidence_refs),
        )


class OutreachCaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    source_creator_run_id: str
    prompt_version: str
    workflow_version: str
    generator_version: str
    max_revisions: int = Field(ge=0)
    policy: OutreachPolicyFixture
    plans: list[OutreachPlanFixture] = Field(min_length=1)
    reviews: list[OutreachReviewFixture] = Field(min_length=1)
    mapping_version: str
    target_base_ref: str
    field_mapping: dict[str, str]
    existing_record: dict[str, str] = Field(default_factory=dict)
    source_checksum_sha256: str = Field(default="", exclude=True)

    def request(self, trigger: CreatorContactTrigger) -> CreatorOutreachRequest:
        return CreatorOutreachRequest(
            trigger=trigger,
            policy=self.policy.domain(),
            source_checksum_sha256=self.source_checksum_sha256,
            prompt_version=self.prompt_version,
            workflow_version=self.workflow_version,
            max_revisions=self.max_revisions,
            mapping_version=self.mapping_version,
            target_base_ref=self.target_base_ref,
            field_mapping=tuple(self.field_mapping.items()),
            existing_record=tuple(self.existing_record.items()),
        )


class ReplyFieldFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str
    status: ReplyFieldStatus
    value: str | None = None
    source_ref: str | None = None
    observed_at: datetime
    supports_criterion: bool | None = None


class ReplyFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    case_id: str
    event_id: str
    outcome: ReplyOutcome
    received_at: datetime
    source_ref: str
    summary: str
    evidence_package_id: str
    cumulative_fields: list[ReplyFieldFixture]
    suggested_response: str | None = None
    event_checksum_sha256: str = Field(default="", exclude=True)

    def domain(self) -> ReplyRecord:
        return ReplyRecord(
            **self.model_dump(exclude={"scenario_id", "case_id", "cumulative_fields"}),
            event_checksum_sha256=self.event_checksum_sha256,
            cumulative_fields=tuple(
                ReplyField(**item.model_dump()) for item in self.cumulative_fields
            ),
        )


class CreatorOutreachFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[CreatorSourceFixture] = Field(min_length=1)
    cases: list[OutreachCaseFixture] = Field(min_length=1)
    replies: list[ReplyFixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> CreatorOutreachFixture:
        source_ids = [item.evaluation.source_run_id for item in self.sources]
        case_ids = [item.case_id for item in self.cases]
        if len(source_ids) != len(set(source_ids)) or len(case_ids) != len(set(case_ids)):
            raise ValueError("Creator source and outreach case IDs must be unique")
        if any(case.source_creator_run_id not in source_ids for case in self.cases):
            raise ValueError("Outreach case references an unknown Creator source run")
        if any(reply.case_id not in case_ids for reply in self.replies):
            raise ValueError("Reply scenario references an unknown outreach case")
        return self

    def reply(self, scenario_id: str) -> ReplyFixture:
        matching = next((item for item in self.replies if item.scenario_id == scenario_id), None)
        if matching is None:
            raise ValueError("Creator reply scenario not found")
        return matching


def load_creator_outreach_fixture(path: Path) -> CreatorOutreachFixture:
    fixture = CreatorOutreachFixture.model_validate_json(path.read_bytes())
    cases = []
    for case in fixture.cases:
        payload = json.dumps(case.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        cases.append(
            case.model_copy(
                update={"source_checksum_sha256": hashlib.sha256(payload.encode()).hexdigest()}
            )
        )
    replies = []
    for reply in fixture.replies:
        payload = json.dumps(reply.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        replies.append(
            reply.model_copy(
                update={"event_checksum_sha256": hashlib.sha256(payload.encode()).hexdigest()}
            )
        )
    return fixture.model_copy(update={"cases": cases, "replies": replies})


__all__ = [
    "CreatorOutreachFixture",
    "OutreachCaseFixture",
    "ReplyFixture",
    "load_creator_outreach_fixture",
]
