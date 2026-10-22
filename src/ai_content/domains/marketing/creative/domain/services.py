"""Domain services - pure business logic, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .entities import CreativeJob
from .value_objects import GenerationBudget


@dataclass(frozen=True)
class ValidationResult:
    """Result of validation."""

    is_valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class GenerationPolicyValidator:
    """Validate generation requests.

    Pure domain service - no external dependencies.
    """

    @staticmethod
    def validate_job_can_approve(job: CreativeJob) -> ValidationResult:
        """Check if a job can be approved."""
        errors = []

        if job.status.value != "awaiting_approval":
            errors.append(f"Expected status AWAITING_APPROVAL, got {job.status.value}")

        successful = job.successful_versions
        if not successful:
            errors.append("No QA-passing version available")
        if job.card is not None:
            expected_refs = job.card.final_version_refs or (job.card.final_version_ref,)
            successful_refs = {version.version_id.value for version in successful}
            if not set(expected_refs).issubset(successful_refs):
                errors.append("Approval card contains a non-passing version")
        if any(
            version.artifact_url is None and version.artifact_path is None for version in successful
        ):
            errors.append("Every version must have an artifact")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=tuple(errors),
        )

    @staticmethod
    def validate_can_retry(job: CreativeJob, budget: GenerationBudget) -> ValidationResult:
        """Backward-compatible retry check used by legacy callers/tests."""
        errors = []

        if job.retry_count >= budget.max_retries:
            errors.append(
                f"Max retries exceeded (max retries={budget.max_retries})",
            )

        current_cost = job.total_cost.amount if job.total_cost else Decimal("0")
        if budget.max_cost is not None and current_cost >= budget.max_cost:
            errors.append(
                f"Budget exceeded (current={current_cost}, max={budget.max_cost})",
            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=tuple(errors),
        )


__all__ = [
    "ValidationResult",
    "GenerationPolicyValidator",
]
