"""Persistence boundary for Performance decision runs."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import (
    CreativeOpportunityAnalysis,
    PerformanceDecisionRun,
    PerformanceEvidencePack,
)


class PerformanceInputDriftError(Exception):
    """A source run identifier was reused for different immutable input."""


class OpportunityAnalysisError(Exception):
    """The optional shadow analysis could not produce a trusted typed result."""


class IPerformanceDecisionRepository(Protocol):
    async def save(self, run: PerformanceDecisionRun) -> None: ...

    async def get(self, run_id: str) -> PerformanceDecisionRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> PerformanceDecisionRun | None: ...

    async def list(self) -> list[PerformanceDecisionRun]: ...


class ICreativeOpportunityAnalyzer(Protocol):
    async def analyze(
        self,
        evidence: PerformanceEvidencePack,
    ) -> CreativeOpportunityAnalysis: ...


__all__ = [
    "ICreativeOpportunityAnalyzer",
    "OpportunityAnalysisError",
    "IPerformanceDecisionRepository",
    "PerformanceInputDriftError",
]
