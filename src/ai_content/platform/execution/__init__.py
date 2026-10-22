"""Persistent local execution primitives for unattended pilot workflows."""

from .celery_scheduler import (
    CELERY_CONTROL_QUEUE,
    CELERY_EXECUTE_COMMAND_TASK,
    CeleryCommandScheduler,
)
from .models import CommandStatus, EnqueueCommand, ExecutionBackend, ExecutionCommand
from .outbox import OutboxMessage, PostgresExecutionOutbox
from .postgres_queue import PostgresCommandQueue
from .queue import (
    CommandQueue,
    CommandScheduler,
    CommandStatusStore,
    QueueCall,
    resolve_queue_call,
)
from .sqlite_queue import CommandPayloadDriftError, SqliteCommandQueue
from .worker import (
    ExecutionWorker,
    PermanentCommandError,
    TransientCommandError,
    WorkerOutcome,
)

__all__ = [
    "CommandPayloadDriftError",
    "CommandQueue",
    "CommandScheduler",
    "CommandStatus",
    "CommandStatusStore",
    "CELERY_CONTROL_QUEUE",
    "CELERY_EXECUTE_COMMAND_TASK",
    "CeleryCommandScheduler",
    "EnqueueCommand",
    "ExecutionBackend",
    "ExecutionCommand",
    "ExecutionWorker",
    "OutboxMessage",
    "PermanentCommandError",
    "PostgresCommandQueue",
    "PostgresExecutionOutbox",
    "QueueCall",
    "SqliteCommandQueue",
    "TransientCommandError",
    "WorkerOutcome",
    "resolve_queue_call",
]
