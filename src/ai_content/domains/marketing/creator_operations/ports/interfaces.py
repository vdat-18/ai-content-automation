"""Persistence boundary for Creator Operations."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import CreatorEvaluationRun


class CreatorInputDriftError(Exception):
    """A source run identifier was reused for different fixture content."""


class ICreatorRunRepository(Protocol):
    async def save(self, run: CreatorEvaluationRun) -> None: ...

    async def get(self, run_id: str) -> CreatorEvaluationRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> CreatorEvaluationRun | None: ...

    async def list(self) -> list[CreatorEvaluationRun]: ...
