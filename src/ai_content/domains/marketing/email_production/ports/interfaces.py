"""External boundaries for Email production."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.models import (
    EmailContextSnapshot,
    EmailPackage,
    EmailPackageVersion,
    EmailProductionJob,
    EmailTrigger,
    SemanticReview,
)


class EmailProductionInputDriftError(ValueError):
    """Raised when an idempotency key is reused with changed input."""


@dataclass(frozen=True)
class PreflightOutcome:
    run_id: str
    evaluation_id: str
    classification: str
    allowed_for_approval: bool
    warnings: tuple[str, ...]


class IEmailPackageGenerator(Protocol):
    @property
    def version(self) -> str: ...

    async def generate(
        self,
        trigger: EmailTrigger,
        context: EmailContextSnapshot,
        revision_instructions: tuple[str, ...],
    ) -> EmailPackage: ...


class IEmailSemanticReviewer(Protocol):
    async def review(
        self,
        package: EmailPackage,
        context: EmailContextSnapshot,
        version_number: int,
    ) -> SemanticReview: ...


class IEmailPreflightGateway(Protocol):
    async def evaluate(
        self,
        job: EmailProductionJob,
        version: EmailPackageVersion,
    ) -> PreflightOutcome: ...


class IEmailProductionRepository(Protocol):
    async def save(self, job: EmailProductionJob) -> None: ...

    async def get(self, job_id: str) -> EmailProductionJob | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> EmailProductionJob | None: ...

    async def list(self) -> list[EmailProductionJob]: ...


__all__ = [
    "EmailProductionInputDriftError",
    "IEmailPackageGenerator",
    "IEmailPreflightGateway",
    "IEmailProductionRepository",
    "IEmailSemanticReviewer",
    "PreflightOutcome",
]
