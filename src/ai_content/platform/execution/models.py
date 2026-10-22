"""Typed records for a persistent command queue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


def _identifier(value: str, name: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable identifier")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


class CommandStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionBackend(StrEnum):
    LEASE_WORKER = "lease_worker"
    CELERY = "celery"
    LEGACY_DBOS = "dbos"


@dataclass(frozen=True)
class EnqueueCommand:
    name: str
    dedupe_key: str
    payload: dict[str, Any]
    workflow_run_id: str | None = None
    max_attempts: int = 3
    queue_name: str = "control"

    def __post_init__(self) -> None:
        _identifier(self.name, "name")
        _identifier(self.dedupe_key, "dedupe_key")
        if self.workflow_run_id is not None:
            _identifier(self.workflow_run_id, "workflow_run_id")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        _identifier(self.queue_name, "queue_name")


@dataclass(frozen=True)
class ExecutionCommand:
    command_id: str
    name: str
    dedupe_key: str
    payload_checksum_sha256: str
    payload: dict[str, Any]
    workflow_run_id: str | None
    status: CommandStatus
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    completed_at: datetime | None = None
    audit_log: tuple[str, ...] = field(default_factory=tuple)
    execution_backend: ExecutionBackend = ExecutionBackend.LEASE_WORKER
    queue_name: str = "control"
    dispatch_generation: int = 0
    execution_id: str | None = None
    started_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("command_id", "name", "dedupe_key"):
            _identifier(getattr(self, name), name)
        if self.workflow_run_id is not None:
            _identifier(self.workflow_run_id, "workflow_run_id")
        _identifier(self.queue_name, "queue_name")
        if self.dispatch_generation < 0:
            raise ValueError("dispatch_generation must not be negative")
        if self.execution_id is not None:
            _identifier(self.execution_id, "execution_id")
        if len(self.payload_checksum_sha256) != 64:
            raise ValueError("payload_checksum_sha256 must be SHA-256")
        if self.attempts < 0 or self.max_attempts < 1 or self.attempts > self.max_attempts:
            raise ValueError("attempt counters are invalid")
        for name in ("created_at", "updated_at", "available_at"):
            _aware(getattr(self, name), name)
        for name in (
            "lease_expires_at",
            "completed_at",
            "started_at",
            "cancel_requested_at",
            "cancelled_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        if self.status == CommandStatus.RUNNING:
            if self.execution_backend == ExecutionBackend.LEASE_WORKER:
                if self.lease_owner is None or self.lease_expires_at is None:
                    raise ValueError("running lease commands require an active lease")
            elif self.execution_id is None:
                raise ValueError("running routed commands require an execution ID")
        elif self.status != CommandStatus.CANCEL_REQUESTED and (
            self.lease_owner is not None or self.lease_expires_at is not None
        ):
            raise ValueError("only running or cancel-requested commands may carry a lease")
        if self.status == CommandStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed commands require completed_at")
        if self.status == CommandStatus.CANCELLED and self.cancelled_at is None:
            raise ValueError("cancelled commands require cancelled_at")


__all__ = ["CommandStatus", "EnqueueCommand", "ExecutionBackend", "ExecutionCommand"]
