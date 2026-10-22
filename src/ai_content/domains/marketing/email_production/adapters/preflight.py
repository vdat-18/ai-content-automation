"""Bridge an exact Email version into the existing N3 health evaluator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime

from ai_content.domains.marketing.email_health.adapters.artifacts import (
    write_email_health_artifacts,
)
from ai_content.domains.marketing.email_health.application.evaluation import (
    EmailHealthRequest,
    RunEmailHealthEvaluation,
)
from ai_content.domains.marketing.email_health.domain.models import (
    EmailHealthRuleSet,
    EmailHealthSubject,
    EmailHealthSubjectType,
    EmailOperationsSnapshot,
    HealthCheckOutcome,
    HealthObservation,
    HealthSeverity,
)
from ai_content.domains.marketing.email_health.ports.interfaces import (
    IEmailHealthRepository,
)
from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import EmailPackageVersion, EmailProductionJob
from ..ports.interfaces import PreflightOutcome


class EmailHealthPreflightGateway:
    def __init__(
        self,
        repository: IEmailHealthRepository,
        artifact_store: ArtifactStore,
        rule_set: EmailHealthRuleSet,
        observations: tuple[HealthObservation, ...],
        observed_at: datetime,
        source_version: str,
        source_system: str,
        integration_id: str | None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._rule_set = rule_set
        self._observations = observations
        self._observed_at = observed_at
        self._source_version = source_version
        self._source_system = source_system
        self._integration_id = integration_id

    async def evaluate(
        self,
        job: EmailProductionJob,
        version: EmailPackageVersion,
    ) -> PreflightOutcome:
        source_run_id = f"email-preflight-{version.version_id}"
        subject = EmailHealthSubject(
            subject_type=EmailHealthSubjectType.CAMPAIGN,
            subject_id=version.version_id,
            brand_id=job.context.brand_id,
            account_id=job.context.account_id,
            source_system=self._source_system,
            integration_id=self._integration_id,
        )
        observations = tuple(
            replace(
                item,
                account_id=job.context.account_id,
                source_system=self._source_system,
                integration_id=self._integration_id,
                source_ref=(
                    version.version_id
                    if item.source_ref == "email-version-pending"
                    else item.source_ref
                ),
            )
            for item in self._observations
        )
        snapshot = EmailOperationsSnapshot(
            snapshot_id=f"snapshot-{version.version_id}",
            subject=subject,
            timezone=job.context.timezone,
            source_version=self._source_version,
            observations=observations,
            observed_at=self._observed_at,
            upstream_report_refs=(version.version_id,),
        )
        canonical = json.dumps(
            {
                "email_version_id": version.version_id,
                "snapshot_id": snapshot.snapshot_id,
                "rule_set_id": self._rule_set.rule_set_id,
                "rule_version": self._rule_set.version,
                "observations": [
                    {
                        "name": item.name.value,
                        "status": item.status.value,
                        "value_type": item.value_type.value,
                        "boolean_value": item.boolean_value,
                        "decimal_value": (
                            str(item.decimal_value) if item.decimal_value is not None else None
                        ),
                        "text_value": item.text_value,
                        "source_ref": item.source_ref,
                        "reason": item.reason,
                    }
                    for item in observations
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        result = await RunEmailHealthEvaluation(self._repository).execute(
            EmailHealthRequest(
                source_run_id=source_run_id,
                source_checksum_sha256=hashlib.sha256(canonical).hexdigest(),
                snapshot=snapshot,
                rule_set=self._rule_set,
            )
        )
        if not result.duplicate:
            write_email_health_artifacts(self._artifact_store, result.run)
        assessments = result.run.evaluation.assessments
        blocking = any(
            item.outcome
            in {HealthCheckOutcome.FAIL, HealthCheckOutcome.UNKNOWN, HealthCheckOutcome.CONFLICT}
            and item.severity == HealthSeverity.BLOCKING
            for item in assessments
        )
        unresolved = any(
            item.outcome in {HealthCheckOutcome.UNKNOWN, HealthCheckOutcome.CONFLICT}
            for item in assessments
        )
        warnings = tuple(
            item.detail
            for item in assessments
            if item.outcome == HealthCheckOutcome.FAIL and item.severity == HealthSeverity.WARNING
        )
        return PreflightOutcome(
            run_id=result.run.run_id,
            evaluation_id=result.run.evaluation.evaluation_id,
            classification=result.run.evaluation.classification.value,
            allowed_for_approval=not blocking and not unresolved,
            warnings=warnings,
        )


__all__ = ["EmailHealthPreflightGateway"]
