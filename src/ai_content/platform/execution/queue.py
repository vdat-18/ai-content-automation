"""Command queue boundary shared by SQLite tests and PostgreSQL runtime."""

from __future__ import annotations

from collections.abc import Awaitable
from inspect import isawaitable
from typing import Any, Protocol, TypeVar, cast

from .models import CommandStatus, EnqueueCommand, ExecutionCommand

T = TypeVar("T")
QueueCall = T | Awaitable[T]


class CommandStatusStore(Protocol):
    def get(self, command_id: str) -> QueueCall[ExecutionCommand | None]: ...

    def get_by_dedupe_key(self, dedupe_key: str) -> QueueCall[ExecutionCommand | None]: ...

    def list(
        self,
        status: CommandStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> QueueCall[list[ExecutionCommand]]: ...


class CommandScheduler(CommandStatusStore, Protocol):
    def enqueue(
        self, request: EnqueueCommand, now: Any = None
    ) -> QueueCall[tuple[ExecutionCommand, bool]]: ...

    def retry_failed(self, command_id: str, **kwargs: Any) -> QueueCall[ExecutionCommand]: ...

    def request_cancel(self, command_id: str, **kwargs: Any) -> QueueCall[ExecutionCommand]: ...

    def close(self) -> None: ...


class CommandQueue(CommandScheduler, Protocol):
    def claim_next(self, worker_id: str, **kwargs: Any) -> QueueCall[ExecutionCommand | None]: ...

    def complete(
        self, command_id: str, worker_id: str, **kwargs: Any
    ) -> QueueCall[ExecutionCommand]: ...

    def renew_lease(
        self, command_id: str, worker_id: str, **kwargs: Any
    ) -> QueueCall[ExecutionCommand]: ...

    def fail(
        self,
        command_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        **kwargs: Any,
    ) -> QueueCall[ExecutionCommand]: ...


async def resolve_queue_call(value: QueueCall[T]) -> T:
    """Resolve an async production call or return a synchronous test result."""
    if isawaitable(value):
        return await cast(Awaitable[T], value)
    return value


__all__ = [
    "CommandQueue",
    "CommandScheduler",
    "CommandStatusStore",
    "QueueCall",
    "resolve_queue_call",
]
