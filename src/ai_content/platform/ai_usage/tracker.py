"""Small lifecycle service used around actual provider calls."""

from dataclasses import replace
from uuid import uuid4

from .interfaces import AIUsageRepository
from .models import AIUsageCompletion, AIUsageFailure, AIUsageStart


class AIUsageTracker:
    def __init__(self, repository: AIUsageRepository) -> None:
        self._repository = repository

    async def start(self, usage: AIUsageStart) -> str:
        event_id = str(uuid4())
        if usage.run_id is None:
            correlation_id = (
                usage.workflow_run_id or usage.job_id or usage.source_run_id or usage.version_id
            )
            if correlation_id is not None:
                usage = replace(usage, run_id=correlation_id)
        await self._repository.start(event_id, usage)
        return event_id

    async def succeed(self, event_id: str, completion: AIUsageCompletion) -> None:
        await self._repository.succeed(event_id, completion)

    async def fail(self, event_id: str, failure: AIUsageFailure) -> None:
        await self._repository.fail(event_id, failure)


__all__ = ["AIUsageTracker"]
