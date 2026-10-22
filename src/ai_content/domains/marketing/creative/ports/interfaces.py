"""Ports - interfaces for external dependencies.

These interfaces define the contract between the domain/application layer
and external implementations (adapters). Domain and application depend on
these ports, not on concrete implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..domain.entities import (
        ApprovalCard,
        AssetVersion,
        CreativeJob,
        CreativeJobId,
        QACheckResult,
        QASession,
        VersionId,
    )
    from ..domain.reviews import SemanticReviewResult
    from .contracts import (
        ContextPackage,
        CreativeWorkItemInput,
        IdeaPackage,
        RevisionRequest,
        SkuInput,
        StaticCreativeInput,
    )


class SemanticReviewError(Exception):
    """Expected semantic reviewer input, service, or response failure."""


class IContextCollector(Protocol):
    """Port: gathers product/customer/brand/history context for one SKU."""

    async def collect(
        self,
        work_item: CreativeWorkItemInput,
        sku: SkuInput,
    ) -> ContextPackage:
        """Collect typed context with evidence refs and data versions.

        Raises when a hard source is missing, times out or breaks the schema.
        """
        ...


class IIdeaGenerator(Protocol):
    """Port: creates candidate idea packages from collected context."""

    async def generate_ideas(
        self,
        context: ContextPackage,
        work_item: CreativeWorkItemInput,
    ) -> tuple[IdeaPackage, ...]:
        """Return one or more typed idea packages with evidence refs."""
        ...


class IImageGenerator(Protocol):
    """Port: Image generator interface for static creative generation."""

    async def generate(
        self,
        input_data: StaticCreativeInput,
        version_id: VersionId,
        revision: RevisionRequest | None = None,
    ) -> AssetVersion:
        """Generate a static image version.

        Args:
            input_data: Contract with all input for generation
            version_id: Identifier for this version
            revision: Previous QA feedback when regenerating; None for v1

        Returns:
            AssetVersion with generated artifact, cost, generator version, seed

        Raises:
            Exception: If generation fails (routed to Operations Queue)
        """
        ...


class IQAChecker(Protocol):
    """Port: QA checker interface for validating creative assets."""

    async def check(self, session: QASession) -> QACheckResult:
        """Run QA checks on an asset version.

        Args:
            session: QA session with asset, input context, rubric, policy

        Returns:
            QACheckResult with pass/fail, score, issues, warnings, feedback;
            non-empty policy_violations route the job to the Policy Queue.
        """
        ...


class ISemanticReviewer(Protocol):
    """Port for model-agnostic semantic assessment of a generated asset."""

    async def review(self, session: QASession) -> SemanticReviewResult: ...


class ICreativeRepository(Protocol):
    """Port: Repository for persisting creative jobs and versions."""

    async def save_job(self, job: CreativeJob) -> None:
        """Save or update a creative job."""
        ...

    async def get_job(self, job_id: CreativeJobId) -> CreativeJob | None:
        """Get a creative job by ID."""
        ...

    async def get_job_by_source_run_id(self, source_run_id: str) -> CreativeJob | None:
        """Get a creative job by its idempotency key."""
        ...

    async def list_jobs(self) -> list[CreativeJob]:
        """List all jobs."""
        ...

    async def save_version(self, version: AssetVersion) -> None:
        """Save an asset version."""
        ...

    async def get_version(self, version_id: VersionId) -> AssetVersion | None:
        """Get an asset version by ID."""
        ...

    async def get_versions_for_job(self, job_id: CreativeJobId) -> list[AssetVersion]:
        """Get all versions for a job, ordered by attempt number."""
        ...


class IApprovalQueue(Protocol):
    """Port: Approval queue for human review."""

    async def submit(self, card: ApprovalCard) -> None:
        """Submit an approval card for human review."""
        ...

    async def process_decision(
        self,
        job_id: CreativeJobId,
        version_id: VersionId,
        decision: str,
        reviewer: str,
        reason: str | None,
    ) -> None:
        """Process an approval decision.

        Args:
            job_id: The job ID
            version_id: The version being decided
            decision: 'approve' or 'reject'
            reviewer: Who made the decision
            reason: Optional reason (required for reject)
        """
        ...


class IExceptionQueue(Protocol):
    """Port: Exception queue for issues requiring intervention."""

    async def create(
        self,
        job_id: CreativeJobId,
        exception_type: str,
        error_message: str,
        suggested_action: str | None,
    ) -> None:
        """Create an exception entry."""
        ...


__all__ = [
    "IContextCollector",
    "IIdeaGenerator",
    "IImageGenerator",
    "IQAChecker",
    "ISemanticReviewer",
    "SemanticReviewError",
    "ICreativeRepository",
    "IApprovalQueue",
    "IExceptionQueue",
]
