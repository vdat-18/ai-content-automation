"""Lease-based command worker for the single-node local pilot."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from loguru import logger

from ai_content.platform.observability.metrics import COMMAND_ATTEMPTS, COMMAND_DURATION

from .models import CommandStatus, ExecutionCommand
from .queue import CommandQueue, resolve_queue_call


class CommandDispatcher(Protocol):
    async def dispatch(self, command: ExecutionCommand) -> None: ...


class PermanentCommandError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TransientCommandError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_delay_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_delay_seconds = retry_delay_seconds


@dataclass(frozen=True)
class WorkerOutcome:
    command_id: str
    status: CommandStatus


class ExecutionWorker:
    def __init__(
        self,
        queue: CommandQueue,
        dispatcher: CommandDispatcher,
        worker_id: str,
        lease_seconds: int = 60,
        retry_delay_seconds: int = 5,
    ) -> None:
        self._queue = queue
        self._dispatcher = dispatcher
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def run_once(self) -> WorkerOutcome | None:
        command = await resolve_queue_call(
            self._queue.claim_next(self._worker_id, lease_seconds=self._lease_seconds)
        )
        if command is None:
            return None
        return await self.run_claimed(command)

    async def run_claimed(self, command: ExecutionCommand) -> WorkerOutcome:
        """Execute a command already claimed by a routed worker such as Celery."""
        started = monotonic()
        with logger.contextualize(
            command_id=command.command_id,
            workflow_run_id=command.workflow_run_id,
        ):
            try:
                await self._dispatch_with_lease_heartbeat(command)
            except TransientCommandError as error:
                COMMAND_ATTEMPTS.labels(command=command.name, outcome="transient_error").inc()
                retry_delay_seconds = (
                    error.retry_delay_seconds
                    if error.retry_delay_seconds is not None
                    else self._retry_delay_seconds
                )
                failed = await resolve_queue_call(
                    self._queue.fail(
                        command.command_id,
                        self._worker_id,
                        error.code,
                        str(error),
                        retryable=True,
                        retry_delay_seconds=retry_delay_seconds,
                    )
                )
                logger.warning(
                    "Execution command {} will retry after {}",
                    command.command_id,
                    error.code,
                )
                return WorkerOutcome(failed.command_id, failed.status)
            except PermanentCommandError as error:
                COMMAND_ATTEMPTS.labels(command=command.name, outcome="permanent_error").inc()
                failed = await resolve_queue_call(
                    self._queue.fail(
                        command.command_id,
                        self._worker_id,
                        error.code,
                        str(error),
                        retryable=False,
                    )
                )
                logger.error("Execution command {} failed: {}", command.command_id, error.code)
                return WorkerOutcome(failed.command_id, failed.status)
            except Exception as error:
                COMMAND_ATTEMPTS.labels(command=command.name, outcome="unexpected_error").inc()
                await resolve_queue_call(
                    self._queue.fail(
                        command.command_id,
                        self._worker_id,
                        "UNEXPECTED",
                        str(error),
                        retryable=False,
                    )
                )
                raise
            else:
                COMMAND_ATTEMPTS.labels(command=command.name, outcome="success").inc()
                completed = await resolve_queue_call(
                    self._queue.complete(command.command_id, self._worker_id)
                )
                logger.info("Execution command {} completed", command.command_id)
                return WorkerOutcome(completed.command_id, completed.status)
            finally:
                COMMAND_DURATION.labels(command=command.name).observe(monotonic() - started)

    async def _dispatch_with_lease_heartbeat(self, command: ExecutionCommand) -> None:
        dispatch = asyncio.create_task(self._dispatcher.dispatch(command))
        heartbeat = asyncio.create_task(self._renew_lease_until_cancelled(command.command_id))
        try:
            done, _ = await asyncio.wait(
                (dispatch, heartbeat),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                await heartbeat
            await dispatch
        finally:
            dispatch.cancel()
            heartbeat.cancel()
            await asyncio.gather(dispatch, heartbeat, return_exceptions=True)

    async def _renew_lease_until_cancelled(self, command_id: str) -> None:
        interval_seconds = max(1.0, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval_seconds)
            await resolve_queue_call(
                self._queue.renew_lease(
                    command_id,
                    self._worker_id,
                    lease_seconds=self._lease_seconds,
                )
            )

    async def run_forever(
        self,
        poll_interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        shutdown = stop_event or asyncio.Event()
        while not shutdown.is_set():
            outcome = await self.run_once()
            if outcome is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(shutdown.wait(), timeout=poll_interval_seconds)


__all__ = [
    "CommandDispatcher",
    "ExecutionWorker",
    "PermanentCommandError",
    "TransientCommandError",
    "WorkerOutcome",
]
