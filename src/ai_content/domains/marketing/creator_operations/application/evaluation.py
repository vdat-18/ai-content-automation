"""Deterministic creator evaluation and data-preview workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ..domain.models import (
    CampaignRequirement,
    CreatorEvaluationRun,
    CreatorProfile,
    CriterionAssessment,
    CriterionOutcome,
    EvaluationState,
    EvaluationVersion,
    EvidenceFact,
    EvidencePackage,
    FieldStatus,
    HandoffState,
    LarkDataPreview,
    PreviewAction,
    PreviewField,
)
from ..ports.interfaces import CreatorInputDriftError, ICreatorRunRepository

_CRITERIA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("location", ("creator_location",)),
    ("persona", ("persona",)),
    ("audience", ("audience",)),
    ("content_home_space", ("content_home_space",)),
    ("product_fit", ("product_fit",)),
    ("deal", ("rate", "availability", "usage_rights")),
)
_REVIEW_REQUIRED = tuple(field for _, fields in _CRITERIA for field in fields)


@dataclass(frozen=True)
class CreatorRunRequest:
    source_run_id: str
    source_checksum_sha256: str
    campaign: CampaignRequirement
    creator: CreatorProfile
    candidate_id: str
    policy_version: str
    location_reference_store_id: str
    location_reference_version: str
    evidence_packages: tuple[EvidencePackage, ...]
    mapping_version: str
    target_base_ref: str
    field_mapping: tuple[tuple[str, str], ...]
    existing_record: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CreatorRunResult:
    run: CreatorEvaluationRun
    duplicate: bool


def _assessment(
    name: str, fields: tuple[str, ...], facts: dict[str, EvidenceFact]
) -> CriterionAssessment:
    selected = [facts.get(field) for field in fields]
    missing = tuple(field for field, fact in zip(fields, selected, strict=True) if fact is None)
    present = [fact for fact in selected if fact is not None]
    refs = tuple(fact.source_ref for fact in present if fact.source_ref)
    if missing or any(fact.status == FieldStatus.UNKNOWN for fact in present):
        unknown = (
            *missing,
            *(fact.field_name for fact in present if fact.status == FieldStatus.UNKNOWN),
        )
        return CriterionAssessment(
            name, CriterionOutcome.UNKNOWN, refs, "Evidence is incomplete.", tuple(unknown)
        )
    if any(fact.status == FieldStatus.CONFLICT for fact in present):
        return CriterionAssessment(
            name, CriterionOutcome.CONFLICT, refs, "Evidence sources conflict."
        )
    if all(fact.status == FieldStatus.NOT_APPLICABLE for fact in present):
        return CriterionAssessment(
            name, CriterionOutcome.NOT_APPLICABLE, refs, "Criterion does not apply."
        )
    if any(fact.supports_criterion is False for fact in present):
        return CriterionAssessment(
            name,
            CriterionOutcome.NOT_SUPPORTED,
            refs,
            "Source evidence does not support this criterion.",
        )
    return CriterionAssessment(
        name, CriterionOutcome.SUPPORTED, refs, "Source evidence supports this criterion."
    )


def evaluate_evidence_package(
    package: EvidencePackage, version: int, policy_version: str
) -> EvaluationVersion:
    facts = {fact.field_name: fact for fact in package.facts}
    criteria = tuple(_assessment(name, fields, facts) for name, fields in _CRITERIA)
    ready = all(
        facts.get(field) is not None
        and facts[field].status in {FieldStatus.KNOWN, FieldStatus.NOT_APPLICABLE}
        for field in _REVIEW_REQUIRED
    )
    identifier = str(uuid5(NAMESPACE_URL, f"creator-evaluation:{package.package_id}:{version}"))
    return EvaluationVersion(
        evaluation_id=identifier,
        version_number=version,
        package_id=package.package_id,
        state=EvaluationState.READY_FOR_REVIEW if ready else EvaluationState.NEEDS_EVIDENCE,
        criteria=criteria,
        created_at=max(fact.observed_at for fact in package.facts),
        policy_version=policy_version,
    )


def build_lark_preview(
    campaign: CampaignRequirement,
    creator: CreatorProfile,
    package: EvidencePackage,
    mapping_version: str,
    target_base_ref: str,
    field_mapping: tuple[tuple[str, str], ...],
    existing_record: tuple[tuple[str, str], ...],
) -> LarkDataPreview:
    facts = {fact.field_name: fact for fact in package.facts}
    existing = dict(existing_record)
    proposals: list[tuple[str, str | None, str | None]] = [
        ("campaign_id", campaign.campaign_id, "campaign requirement"),
        ("creator_id", creator.creator_id, "creator identity"),
    ]
    for source_field, target_field in field_mapping:
        fact = facts.get(source_field)
        if fact is None or fact.status == FieldStatus.UNKNOWN:
            proposals.append((target_field, None, None))
        elif fact.status == FieldStatus.CONFLICT:
            proposals.append((target_field, fact.value, fact.source_ref))
        elif fact.status == FieldStatus.NOT_APPLICABLE:
            continue
        else:
            proposals.append((target_field, fact.value, fact.source_ref))

    fields: list[PreviewField] = []
    for target, proposed, source in proposals:
        current = existing.get(target)
        fact = next((facts.get(key) for key, mapped in field_mapping if mapped == target), None)
        if fact is not None and fact.status == FieldStatus.CONFLICT:
            action = PreviewAction.CONFLICT
        elif proposed is None:
            action = PreviewAction.SKIP_UNKNOWN
        elif current is None:
            action = PreviewAction.CREATE
        elif current == proposed:
            action = PreviewAction.UNCHANGED
        else:
            action = PreviewAction.UPDATE
        fields.append(PreviewField(target, current, proposed, action, source))
    state = (
        HandoffState.BLOCKED_CONFLICT
        if any(field.action == PreviewAction.CONFLICT for field in fields)
        else HandoffState.PREVIEW_READY
    )
    return LarkDataPreview(mapping_version, target_base_ref, state, tuple(fields))


@dataclass(frozen=True)
class AppendCreatorEvidenceRequest:
    run_id: str
    expected_evaluation_id: str
    evidence_package: EvidencePackage
    mapping_version: str
    target_base_ref: str
    field_mapping: tuple[tuple[str, str], ...]
    existing_record: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class AppendCreatorEvidenceResult:
    run: CreatorEvaluationRun
    duplicate: bool = False


class AppendCreatorEvidence:
    def __init__(self, repository: ICreatorRunRepository) -> None:
        self._repository = repository

    async def execute(self, request: AppendCreatorEvidenceRequest) -> AppendCreatorEvidenceResult:
        run = await self._repository.get(request.run_id)
        if run is None:
            raise ValueError("Creator evaluation run not found")
        if any(
            evaluation.package_id == request.evidence_package.package_id
            for evaluation in run.evaluations
        ):
            return AppendCreatorEvidenceResult(run, True)
        if run.latest_evaluation.evaluation_id != request.expected_evaluation_id:
            raise ValueError("Reply evidence must extend the latest evaluation version")
        evaluation = evaluate_evidence_package(
            request.evidence_package, len(run.evaluations) + 1, run.policy_version
        )
        preview = build_lark_preview(
            run.campaign,
            run.creator,
            request.evidence_package,
            request.mapping_version,
            request.target_base_ref,
            request.field_mapping,
            request.existing_record,
        )
        updated = replace(
            run,
            evaluations=(*run.evaluations, evaluation),
            preview=preview,
            audit_log=(*run.audit_log, f"evidence_appended:{evaluation.evaluation_id}"),
        )
        await self._repository.save(updated)
        return AppendCreatorEvidenceResult(updated)


class RunCreatorEvaluation:
    def __init__(self, repository: ICreatorRunRepository) -> None:
        self._repository = repository

    async def execute(self, request: CreatorRunRequest) -> CreatorRunResult:
        existing = await self._repository.get_by_source_run_id(request.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise CreatorInputDriftError(
                    f"source_run_id {request.source_run_id!r} was reused with changed input"
                )
            return CreatorRunResult(existing, True)
        for prior in await self._repository.list():
            if prior.candidate_id == request.candidate_id:
                raise ValueError("Candidate ID already belongs to another source run")
        if not request.evidence_packages:
            raise ValueError("At least one evidence package is required")
        if request.location_reference_store_id != request.campaign.store_id:
            raise ValueError("Customer-location reference belongs to a different store")
        evaluations = tuple(
            evaluate_evidence_package(package, index, request.policy_version)
            for index, package in enumerate(request.evidence_packages, start=1)
        )
        created_at = datetime.now(UTC)
        run_id = str(uuid5(NAMESPACE_URL, f"creator-run:{request.source_run_id}"))
        run = CreatorEvaluationRun(
            run_id=run_id,
            source_run_id=request.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            campaign=request.campaign,
            creator=request.creator,
            candidate_id=request.candidate_id,
            policy_version=request.policy_version,
            location_reference_store_id=request.location_reference_store_id,
            location_reference_version=request.location_reference_version,
            evaluations=evaluations,
            preview=build_lark_preview(
                request.campaign,
                request.creator,
                request.evidence_packages[-1],
                request.mapping_version,
                request.target_base_ref,
                request.field_mapping,
                request.existing_record,
            ),
            created_at=created_at,
            audit_log=tuple(f"evaluation:{item.evaluation_id}" for item in evaluations),
        )
        await self._repository.save(run)
        return CreatorRunResult(run, False)


__all__ = [
    "AppendCreatorEvidence",
    "AppendCreatorEvidenceRequest",
    "AppendCreatorEvidenceResult",
    "CreatorRunRequest",
    "CreatorRunResult",
    "RunCreatorEvaluation",
    "build_lark_preview",
    "evaluate_evidence_package",
]
