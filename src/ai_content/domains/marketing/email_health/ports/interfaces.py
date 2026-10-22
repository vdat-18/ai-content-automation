"""Persistence boundary for Email Operations health runs."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import EmailHealthRun


class EmailHealthInputDriftError(Exception):
    """A source run identifier was reused with different immutable input."""


class IEmailHealthRepository(Protocol):
    async def save(self, run: EmailHealthRun) -> None: ...

    async def get(self, run_id: str) -> EmailHealthRun | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> EmailHealthRun | None: ...

    async def list(self) -> list[EmailHealthRun]: ...


__all__ = ["EmailHealthInputDriftError", "IEmailHealthRepository"]
