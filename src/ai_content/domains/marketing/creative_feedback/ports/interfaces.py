"""Persistence boundary for Creative feedback runs."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import AdsEvidencePack, CreativeFeedbackRun, PerformanceLearningAnalysis


class CreativeFeedbackInputDriftError(Exception):
    """A source run identifier was reused with different immutable input."""


class PerformanceLearningAnalysisError(Exception):
    """The optional shadow learning model failed at its system boundary."""


class IPerformanceLearningAnalyzer(Protocol):
    async def analyze(self, evidence: AdsEvidencePack) -> PerformanceLearningAnalysis: ...


class ICreativeFeedbackRepository(Protocol):
    async def save(self, run: CreativeFeedbackRun) -> None: ...

    async def get(self, run_id: str) -> CreativeFeedbackRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeFeedbackRun | None: ...

    async def list(self) -> list[CreativeFeedbackRun]: ...

    async def list_approved_memory(
        self,
        *,
        brand_id: str,
        sku_id: str,
        limit: int = 20,
    ) -> list[CreativeFeedbackRun]: ...


__all__ = [
    "CreativeFeedbackInputDriftError",
    "ICreativeFeedbackRepository",
    "IPerformanceLearningAnalyzer",
    "PerformanceLearningAnalysisError",
]
