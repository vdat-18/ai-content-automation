"""Durable commands for read-only data-source synchronization."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_content.platform.execution import (
    CommandScheduler,
    CommandStatus,
    EnqueueCommand,
    ExecutionCommand,
    PermanentCommandError,
    TransientCommandError,
    resolve_queue_call,
)

from .bootstrap import DataSourceRuntime
from .domain.models import SyncStatus


class DataSourceCommandName(StrEnum):
    SYNC = "data_sources.sync"


class SyncDataSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] = Field(min_length=1)


_ACTIVE_SYNC_STATUSES = {
    CommandStatus.PENDING,
    CommandStatus.RUNNING,
    CommandStatus.RETRY_WAIT,
    CommandStatus.CANCEL_REQUESTED,
}


def sync_data_sources_command(batch_id: str, source_ids: tuple[str, ...]) -> EnqueueCommand:
    payload = SyncDataSourcesPayload(source_ids=list(dict.fromkeys(source_ids)))
    return EnqueueCommand(
        name=DataSourceCommandName.SYNC.value,
        dedupe_key=f"data-sources:sync:{batch_id}",
        payload=payload.model_dump(mode="json"),
        workflow_run_id=batch_id,
        max_attempts=1,
    )


def sync_command_sources(command: ExecutionCommand) -> tuple[str, ...]:
    if command.name != DataSourceCommandName.SYNC.value:
        return ()
    try:
        payload = SyncDataSourcesPayload.model_validate(command.payload)
    except ValueError:
        return ()
    return tuple(payload.source_ids)


def is_active_data_source_sync(command: ExecutionCommand) -> bool:
    return (
        command.name == DataSourceCommandName.SYNC.value and command.status in _ACTIVE_SYNC_STATUSES
    )


async def enqueue_data_source_sync(
    queue: CommandScheduler,
    source_ids: tuple[str, ...],
) -> tuple[ExecutionCommand, bool]:
    commands = await resolve_queue_call(queue.list())
    for command in commands:
        if not is_active_data_source_sync(command):
            continue
        if set(source_ids).intersection(sync_command_sources(command)):
            return command, False
    batch_id = f"data-source-sync-{uuid4().hex}"
    return await resolve_queue_call(queue.enqueue(sync_data_sources_command(batch_id, source_ids)))


class DataSourceCommandDispatcher:
    def __init__(self, runtime: DataSourceRuntime) -> None:
        self._runtime = runtime

    async def dispatch(self, command: ExecutionCommand) -> None:
        if command.name != DataSourceCommandName.SYNC.value:
            raise ValueError(f"Unsupported data-source command: {command.name}")
        try:
            payload = SyncDataSourcesPayload.model_validate(command.payload)
        except ValidationError as error:
            raise PermanentCommandError(
                "INVALID_DATA_SOURCE_SYNC_COMMAND",
                "Data-source sync command payload is invalid",
            ) from error

        failed_runs = []
        for source_id in payload.source_ids:
            try:
                run = await self._runtime.sync(source_id)
            except KeyError as error:
                raise PermanentCommandError(
                    "DATA_SOURCE_NOT_CONFIGURED",
                    f"Data source {source_id} is not configured",
                ) from error
            if run.status == SyncStatus.FAILED:
                failed_runs.append(run)

        if not failed_runs:
            return
        first = failed_runs[0]
        message = first.error_message or "Data-source synchronization failed"
        if first.error_code in {"RATE_LIMITED", "SOURCE_UNAVAILABLE"}:
            raise TransientCommandError(first.error_code, message)
        raise PermanentCommandError(first.error_code or "DATA_SOURCE_SYNC_FAILED", message)


__all__ = [
    "DataSourceCommandDispatcher",
    "DataSourceCommandName",
    "SyncDataSourcesPayload",
    "enqueue_data_source_sync",
    "is_active_data_source_sync",
    "sync_data_sources_command",
    "sync_command_sources",
]
