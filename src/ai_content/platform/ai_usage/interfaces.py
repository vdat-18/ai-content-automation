"""Persistence boundary for durable AI usage accounting."""

from typing import Protocol

from .models import (
    AIUsageCompletion,
    AIUsageEvent,
    AIUsageEventPage,
    AIUsageFailure,
    AIUsageFilters,
    AIUsageRunPage,
    AIUsageStart,
    AIUsageSummary,
)


class AIUsageRepository(Protocol):
    async def start(self, event_id: str, usage: AIUsageStart) -> AIUsageEvent: ...

    async def succeed(self, event_id: str, completion: AIUsageCompletion) -> None: ...

    async def fail(self, event_id: str, failure: AIUsageFailure) -> None: ...

    async def summary(self, filters: AIUsageFilters) -> AIUsageSummary: ...

    async def list_events(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageEventPage: ...

    async def get_event(self, event_id: str) -> AIUsageEvent | None: ...

    async def list_runs(
        self, filters: AIUsageFilters, *, limit: int, offset: int
    ) -> AIUsageRunPage: ...

    def close(self) -> None: ...


__all__ = ["AIUsageRepository"]
