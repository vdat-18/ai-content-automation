"""Deterministic Email Operations health evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from ..domain.models import (
    EmailHealthClassification,
    EmailHealthEvaluation,
    EmailHealthEvaluationState,
    EmailHealthRule,
    EmailHealthRuleSet,
    EmailHealthRun,
    EmailOperationsSnapshot,
    HealthCheckAssessment,
    HealthCheckOutcome,
    HealthObservation,
    HealthObservationName,
    HealthRuleOperator,
    HealthSeverity,
    IssueState,
    ObservationStatus,
    ObservationValueType,
    RemediationAction,
    RemediationPreview,
    RemediationPreviewState,
)
from ..ports.interfaces import EmailHealthInputDriftError, IEmailHealthRepository

_CLASSIFICATION_PRIORITY = {
    EmailHealthClassification.BLOCKED: 30,
    EmailHealthClassification.DATA_HEALTH_EXCEPTION: 20,
    EmailHealthClassification.WARNING: 10,
}

_CHECKLISTS = {
    RemediationAction.CORRECT_CONFIGURATION: (
        "Inspect the exact account and entity configuration referenced by the failed checks.",
        "Prepare a corrected configuration preview without changing the live Klaviyo object.",
        "Obtain owner approval before any external write.",
        "Re-run the same checks with a new evidence snapshot after correction.",
    ),
    RemediationAction.INVESTIGATE_SOURCE: (
        "Confirm account, integration and stable metric identifiers.",
        "Check event freshness and source health without interpreting unknown revenue as zero.",
        "Reconcile the corrected aggregate snapshot with the N2 report when applicable.",
        "Attach a new evidence reference before marking the issue resolved.",
    ),
    RemediationAction.REVIEW_DELIVERABILITY: (
        "Inspect the native Klaviyo deliverability evidence for the exact account and message.",
        "Compare the active policy threshold with the native benchmark without merging them.",
        "Prepare an owner-reviewed mitigation plan; do not change audience or sending state.",
        "Verify the result using a later aggregate snapshot.",
    ),
    RemediationAction.REQUEST_EVIDENCE: (
        "Collect the missing account-scoped evidence listed by the evaluation.",
        "Resolve observations by stable IDs rather than display names.",
        "Run a new immutable evaluation after evidence is available.",
    ),
    RemediationAction.MANUAL_REVIEW: (
        "Resolve conflicting source evidence for the same account and entity.",
        "Document which source and identifier are authoritative.",
        "Run a new immutable evaluation after the conflict is resolved.",
    ),
}


@dataclass(frozen=True)
class EmailHealthRequest:
    source_run_id: str
    source_checksum_sha256: str
    snapshot: EmailOperationsSnapshot
    rule_set: EmailHealthRuleSet


@dataclass(frozen=True)
class EmailHealthResult:
    run: EmailHealthRun
    duplicate: bool


def _known_passes(rule: EmailHealthRule, observation: HealthObservation) -> bool:
    if rule.operator == HealthRuleOperator.IS_TRUE:
        return observation.boolean_value is True
    if rule.operator == HealthRuleOperator.IS_FALSE:
        return observation.boolean_value is False
    if rule.operator == HealthRuleOperator.EQUALS:
        return observation.text_value == rule.expected_text
    assert observation.decimal_value is not None
    assert rule.threshold_decimal is not None
    value: Decimal = observation.decimal_value
    threshold = rule.threshold_decimal
    if rule.operator == HealthRuleOperator.LESS_THAN:
        return value < threshold
    if rule.operator == HealthRuleOperator.LESS_THAN_OR_EQUAL:
        return value <= threshold
    if rule.operator == HealthRuleOperator.GREATER_THAN:
        return value > threshold
    return value >= threshold


def _expected_value(rule: EmailHealthRule) -> str:
    value = (
        rule.expected_boolean
        if rule.expected_boolean is not None
        else rule.threshold_decimal
        if rule.threshold_decimal is not None
        else rule.expected_text
    )
    return str(value)


def _observed_value(observation: HealthObservation | None) -> str | None:
    if observation is None or observation.status != ObservationStatus.KNOWN:
        return None
    value = (
        observation.boolean_value
        if observation.boolean_value is not None
        else observation.decimal_value
        if observation.decimal_value is not None
        else observation.text_value
    )
    return str(value)


def _assessment(
    rule: EmailHealthRule,
    observation: HealthObservation | None,
    outcome: HealthCheckOutcome,
    detail: str,
    sample_value: Decimal | None = None,
) -> HealthCheckAssessment:
    return HealthCheckAssessment(
        rule_id=rule.rule_id,
        observation=rule.observation,
        outcome=outcome,
        severity=rule.severity,
        operator=rule.operator,
        expected_value=_expected_value(rule),
        observed_value=_observed_value(observation),
        sample_observation=rule.sample_observation,
        sample_value=sample_value,
        source_ref=observation.source_ref if observation else None,
        detail=detail,
    )


def _assess(
    rule: EmailHealthRule,
    observations: dict[HealthObservationName, HealthObservation],
) -> HealthCheckAssessment:
    observation = observations.get(rule.observation)
    if observation is None or observation.status == ObservationStatus.UNKNOWN:
        return _assessment(
            rule,
            observation,
            HealthCheckOutcome.UNKNOWN,
            observation.reason if observation else "Required observation is unavailable.",
        )
    if observation.status == ObservationStatus.CONFLICT:
        return _assessment(
            rule,
            observation,
            HealthCheckOutcome.CONFLICT,
            observation.reason or "Observation sources conflict.",
        )
    if observation.status == ObservationStatus.NOT_APPLICABLE:
        return _assessment(
            rule,
            observation,
            HealthCheckOutcome.NOT_APPLICABLE,
            observation.reason or "Observation is not applicable.",
        )
    expected_type = (
        ObservationValueType.BOOLEAN
        if rule.operator in {HealthRuleOperator.IS_TRUE, HealthRuleOperator.IS_FALSE}
        else ObservationValueType.TEXT
        if rule.operator == HealthRuleOperator.EQUALS
        else ObservationValueType.DECIMAL
    )
    if observation.value_type != expected_type:
        return _assessment(
            rule,
            observation,
            HealthCheckOutcome.CONFLICT,
            "Observation value type does not match the versioned rule.",
        )
    sample_value = None
    if rule.sample_observation is not None:
        sample = observations.get(rule.sample_observation)
        if sample is None or sample.status == ObservationStatus.UNKNOWN:
            return _assessment(
                rule,
                observation,
                HealthCheckOutcome.UNKNOWN,
                "Required sample evidence is unavailable.",
            )
        if sample.status == ObservationStatus.CONFLICT:
            return _assessment(
                rule,
                observation,
                HealthCheckOutcome.CONFLICT,
                "Sample evidence sources conflict.",
            )
        if (
            sample.status != ObservationStatus.KNOWN
            or sample.value_type != ObservationValueType.DECIMAL
            or sample.decimal_value is None
        ):
            return _assessment(
                rule,
                observation,
                HealthCheckOutcome.UNKNOWN,
                "Sample evidence is not a known numeric count.",
            )
        sample_value = sample.decimal_value
        assert rule.minimum_sample is not None
        if sample_value < rule.minimum_sample:
            return _assessment(
                rule,
                observation,
                HealthCheckOutcome.UNKNOWN,
                f"Sample {sample_value} is below required minimum {rule.minimum_sample}.",
                sample_value,
            )
    passed = _known_passes(rule, observation)
    return _assessment(
        rule,
        observation,
        HealthCheckOutcome.PASS if passed else HealthCheckOutcome.FAIL,
        "Check passed." if passed else rule.description,
        sample_value,
    )


def _preview(
    run_id: str,
    evaluation: EmailHealthEvaluation,
) -> RemediationPreview | None:
    if evaluation.recommendation == RemediationAction.NONE:
        return None
    checklist = _CHECKLISTS[evaluation.recommendation]
    return RemediationPreview(
        preview_id=str(uuid5(NAMESPACE_URL, f"email-health-preview:{run_id}")),
        state=RemediationPreviewState.NOT_RELEASED,
        source_run_id=run_id,
        source_evaluation_id=evaluation.evaluation_id,
        action=evaluation.recommendation,
        checklist=checklist,
        evidence_refs=evaluation.evidence_refs,
        missing_evidence=evaluation.missing_observations,
        prohibited_external_actions=(
            "send_or_schedule_campaign",
            "change_flow_configuration",
            "change_segment_or_suppression",
            "change_coupon",
            "dismiss_native_alert",
        ),
    )


class RunEmailHealthEvaluation:
    def __init__(self, repository: IEmailHealthRepository) -> None:
        self._repository = repository

    async def execute(self, request: EmailHealthRequest) -> EmailHealthResult:
        existing = await self._repository.get_by_source_run_id(request.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise EmailHealthInputDriftError(
                    f"source_run_id {request.source_run_id!r} was reused with changed input"
                )
            return EmailHealthResult(existing, True)
        if request.snapshot.observed_at < request.rule_set.effective_at:
            raise ValueError("Rule set is not effective for the snapshot timestamp")
        rules = tuple(
            rule
            for rule in request.rule_set.rules
            if rule.subject_type == request.snapshot.subject.subject_type
        )
        if not rules:
            raise ValueError("Rule set does not support this Email Operations subject type")
        observations = {item.name: item for item in request.snapshot.observations}
        assessments = tuple(_assess(rule, observations) for rule in rules)
        failures = [item for item in assessments if item.outcome == HealthCheckOutcome.FAIL]
        conflicts = [item for item in assessments if item.outcome == HealthCheckOutcome.CONFLICT]
        unknowns = [item for item in assessments if item.outcome == HealthCheckOutcome.UNKNOWN]
        rules_by_id = {rule.rule_id: rule for rule in rules}
        if conflicts:
            state = EmailHealthEvaluationState.BLOCKED_CONFLICT
            classification = EmailHealthClassification.CONFLICTING_EVIDENCE
            recommendation = RemediationAction.MANUAL_REVIEW
        elif unknowns:
            state = EmailHealthEvaluationState.NEEDS_EVIDENCE
            classification = EmailHealthClassification.INSUFFICIENT_EVIDENCE
            recommendation = RemediationAction.REQUEST_EVIDENCE
        elif failures:
            selected = max(
                failures,
                key=lambda item: (
                    1 if item.severity == HealthSeverity.BLOCKING else 0,
                    _CLASSIFICATION_PRIORITY[rules_by_id[item.rule_id].failure_classification],
                ),
            )
            selected_rule = rules_by_id[selected.rule_id]
            state = EmailHealthEvaluationState.READY_FOR_TRIAGE
            classification = selected_rule.failure_classification
            recommendation = selected_rule.recommendation
        else:
            state = EmailHealthEvaluationState.HEALTHY
            classification = EmailHealthClassification.HEALTHY
            recommendation = RemediationAction.NONE
        evidence_refs = tuple(
            dict.fromkeys(
                item.source_ref for item in request.snapshot.observations if item.source_ref
            )
        )
        missing = tuple(dict.fromkeys(item.observation for item in unknowns))
        evaluation_id = str(
            uuid5(
                NAMESPACE_URL,
                f"email-health-evaluation:{request.source_run_id}:"
                f"{request.rule_set.rule_set_id}:{request.rule_set.version}",
            )
        )
        created_at = datetime.now(UTC)
        evaluation = EmailHealthEvaluation(
            evaluation_id=evaluation_id,
            version_number=1,
            state=state,
            classification=classification,
            recommendation=recommendation,
            rule_set_id=request.rule_set.rule_set_id,
            rule_version=request.rule_set.version,
            rule_status=request.rule_set.status,
            rule_source=request.rule_set.source,
            assessments=assessments,
            evidence_refs=evidence_refs,
            missing_observations=missing,
            created_at=created_at,
        )
        run_id = str(uuid5(NAMESPACE_URL, f"email-health:{request.source_run_id}"))
        issue_basis = ":".join(
            (
                request.snapshot.subject.account_id,
                request.snapshot.subject.subject_type.value,
                request.snapshot.subject.subject_id,
                *sorted(
                    item.rule_id
                    for item in assessments
                    if item.outcome
                    in {
                        HealthCheckOutcome.FAIL,
                        HealthCheckOutcome.UNKNOWN,
                        HealthCheckOutcome.CONFLICT,
                    }
                ),
            )
        )
        issue_fingerprint = "eh-" + hashlib.sha256(issue_basis.encode()).hexdigest()[:32]
        run = EmailHealthRun(
            run_id=run_id,
            source_run_id=request.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            issue_fingerprint=issue_fingerprint,
            snapshot=request.snapshot,
            evaluation=evaluation,
            created_at=created_at,
            issue_state=(
                IssueState.HEALTHY
                if evaluation.state == EmailHealthEvaluationState.HEALTHY
                else IssueState.OPEN
            ),
            remediation_preview=_preview(run_id, evaluation),
            audit_log=(f"evaluation:{evaluation_id}",),
        )
        await self._repository.save(run)
        return EmailHealthResult(run, False)


__all__ = [
    "EmailHealthRequest",
    "EmailHealthResult",
    "RunEmailHealthEvaluation",
]
