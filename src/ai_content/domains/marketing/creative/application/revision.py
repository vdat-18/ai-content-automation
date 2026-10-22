"""Build bounded image revision requests from structured QA evidence."""

from __future__ import annotations

from ..domain.entities import AssetVersion, QACheckResult
from ..domain.reviews import CriterionStatus, RepairAction
from ..ports.contracts import RevisionRequest, SkuInput


class RevisionPlanningError(Exception):
    """QA result cannot be converted into a safe automated revision."""

    def __init__(self, message: str, code: str = "revision_requires_human_review") -> None:
        super().__init__(message)
        self.code = code


class PlanCreativeRevision:
    """Translate reviewer evidence into one constrained regeneration request."""

    _SUPPORTED_ACTIONS = {
        RepairAction.REGENERATE_FULL,
        RepairAction.REGENERATE_WITH_CONSTRAINTS,
    }
    _HUMAN_ACTIONS = {
        RepairAction.EDIT_REGION,
        RepairAction.MANUAL_REVIEW,
        RepairAction.REJECT_POLICY,
    }

    def plan(
        self,
        version: AssetVersion,
        qa_result: QACheckResult,
        sku: SkuInput,
    ) -> RevisionRequest:
        if qa_result.requires_human_review or not qa_result.retryable:
            raise RevisionPlanningError("QA result does not permit an automated revision")
        if set(qa_result.repair_actions) & self._HUMAN_ACTIONS:
            raise RevisionPlanningError("Requested repair action is not safely automated")
        unsupported = set(qa_result.repair_actions) - self._SUPPORTED_ACTIONS
        if unsupported:
            raise RevisionPlanningError("QA returned an unsupported repair action")

        failed_criteria = tuple(
            item.criterion_id for item in qa_result.criteria if item.status == CriterionStatus.FAIL
        )
        instructions = tuple(
            dict.fromkeys(
                item.description.strip()
                for item in qa_result.semantic_issues
                if item.description.strip()
            )
        )
        if not instructions and qa_result.feedback:
            instructions = (qa_result.feedback.strip(),)
        if not instructions:
            instructions = tuple(qa_result.issues)

        spec = sku.creative_constraints.format_spec
        immutable = (
            (f"brand guideline: {sku.creative_constraints.brand_guideline_ref or 'default'}",)
            + tuple(f"banned claim: {claim}" for claim in sku.creative_constraints.banned_claims)
            + (f"format: {spec.width}x{spec.height} {spec.file_format}",)
        )
        repair_actions = qa_result.repair_actions or (RepairAction.REGENERATE_WITH_CONSTRAINTS,)
        return RevisionRequest(
            previous_version_ref=version.version_id.value,
            issues=qa_result.issues,
            feedback=qa_result.feedback,
            immutable_constraints=immutable,
            allowed_changes=failed_criteria or qa_result.issues,
            repair_actions=repair_actions,
            evidence_refs=qa_result.evidence_refs,
            instructions=instructions,
            failed_criteria=failed_criteria,
        )


__all__ = ["PlanCreativeRevision", "RevisionPlanningError"]
