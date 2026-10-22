"""API contracts for persistent local execution commands."""

from pydantic import BaseModel, Field


class ExecutionCommandResponse(BaseModel):
    command_id: str
    name: str
    workflow_run_id: str | None
    status: str
    attempts: int
    max_attempts: int
    created_at: str
    updated_at: str
    available_at: str
    lease_expires_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    completed_at: str | None
    execution_backend: str
    queue_name: str
    dispatch_generation: int
    execution_id: str | None
    started_at: str | None
    cancel_requested_at: str | None
    cancelled_at: str | None
    audit_log: list[str]


class ExecutionCommandListResponse(BaseModel):
    items: list[ExecutionCommandResponse]
    total: int


class CommandAcceptedResponse(BaseModel):
    command: ExecutionCommandResponse
    created: bool


class CreativeLoopStartCommandRequest(BaseModel):
    input_snapshot_id: str = Field(min_length=1)


__all__ = [
    "CommandAcceptedResponse",
    "CreativeLoopStartCommandRequest",
    "ExecutionCommandListResponse",
    "ExecutionCommandResponse",
]
