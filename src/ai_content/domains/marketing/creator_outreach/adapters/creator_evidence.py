"""Append sanitized reply evidence to the exact Creator evaluation run."""

from __future__ import annotations

from ai_content.domains.marketing.creator_operations.adapters.artifacts import (
    write_creator_artifacts,
)
from ai_content.domains.marketing.creator_operations.application.evaluation import (
    AppendCreatorEvidence,
    AppendCreatorEvidenceRequest,
)
from ai_content.domains.marketing.creator_operations.domain.models import (
    EvidenceFact,
    EvidencePackage,
    FieldStatus,
)
from ai_content.domains.marketing.creator_operations.ports.interfaces import (
    ICreatorRunRepository,
)
from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreatorEvaluationUpdate, CreatorOutreachRun, ReplyRecord


class CreatorOperationsEvidenceAppender:
    def __init__(self, repository: ICreatorRunRepository, artifact_store: ArtifactStore) -> None:
        self._repository = repository
        self._artifact_store = artifact_store

    async def append(self, run: CreatorOutreachRun, reply: ReplyRecord) -> CreatorEvaluationUpdate:
        package = EvidencePackage(
            package_id=reply.evidence_package_id,
            stage="reply_evidence",
            facts=tuple(
                EvidenceFact(
                    field_name=item.field_name,
                    status=FieldStatus(item.status.value),
                    value=item.value,
                    source_ref=item.source_ref,
                    observed_at=item.observed_at,
                    supports_criterion=item.supports_criterion,
                )
                for item in reply.cumulative_fields
            ),
        )
        result = await AppendCreatorEvidence(self._repository).execute(
            AppendCreatorEvidenceRequest(
                run_id=run.trigger.creator_run_id,
                expected_evaluation_id=run.trigger.evaluation_id,
                evidence_package=package,
                mapping_version=run.mapping_version,
                target_base_ref=run.target_base_ref,
                field_mapping=run.field_mapping,
                existing_record=run.existing_record,
            )
        )
        write_creator_artifacts(self._artifact_store, result.run)
        latest = result.run.latest_evaluation
        missing = tuple(
            dict.fromkeys(
                field for criterion in latest.criteria for field in criterion.missing_fields
            )
        )
        return CreatorEvaluationUpdate(
            evaluation_id=latest.evaluation_id,
            evaluation_state=latest.state.value,
            lark_preview_state=result.run.preview.state.value,
            missing_fields=missing,
            preview_ref=(f"creator-operations/{result.run.source_run_id}/lark_preview.md"),
        )


__all__ = ["CreatorOperationsEvidenceAppender"]
