"""Persistence contract for Creative loop orchestration."""

from typing import Protocol

from ..domain.models import CreativeLoopRun


class CreativeLoopInputDriftError(Exception):
    """A stable source identity was reused with different input."""


class CreativeLoopEventDriftError(Exception):
    """A stable event identity was reused with different evidence."""


class ICreativeLoopRepository(Protocol):
    async def save(self, run: CreativeLoopRun) -> None: ...

    async def get(self, run_id: str) -> CreativeLoopRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeLoopRun | None: ...

    async def list(self) -> list[CreativeLoopRun]: ...


__all__ = [
    "CreativeLoopEventDriftError",
    "CreativeLoopInputDriftError",
    "ICreativeLoopRepository",
]
