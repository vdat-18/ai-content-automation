"""Persistence boundary for Creative intake runs."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import CreativeIntakeRun


class CreativeIntakeInputDriftError(Exception):
    """A released trigger was reused with different immutable context."""


class ICreativeIntakeRepository(Protocol):
    async def save(self, run: CreativeIntakeRun) -> None: ...

    async def get(self, run_id: str) -> CreativeIntakeRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeIntakeRun | None: ...

    async def list(self) -> list[CreativeIntakeRun]: ...


__all__ = ["CreativeIntakeInputDriftError", "ICreativeIntakeRepository"]
