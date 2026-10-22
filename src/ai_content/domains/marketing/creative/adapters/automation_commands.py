"""Durable command boundary for one selected-SKU Creative automation job."""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum

from loguru import logger
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from ai_content.domains.marketing.creative.ports.contracts import (
    MarketingCreativeAutomationRequest,
)
from ai_content.platform.execution import (
    CommandScheduler,
    EnqueueCommand,
    ExecutionCommand,
    PermanentCommandError,
    QueueCall,
    TransientCommandError,
)

_REQUEST_ADAPTER = TypeAdapter(MarketingCreativeAutomationRequest)


class CreativeAutomationCommandName(StrEnum):
    PROCESS_SKU = "creative_automation.process_sku"
    GENERATE_AGAIN = "creative_automation.generate_again"


class ProcessSkuPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    request: dict[str, object]
    snapshot_ids: list[str]


class GenerateAgainPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    generation_request_id: str


class CreativeAutomationCommandService:
    def __init__(self, scheduler: CommandScheduler) -> None:
        self._scheduler = scheduler

    def enqueue_process_sku(
        self,
        batch_id: str,
        request: MarketingCreativeAutomationRequest,
        snapshot_ids: tuple[str, ...],
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        return self._scheduler.enqueue(process_sku_command(batch_id, request, snapshot_ids))

    def enqueue_generate_again(
        self,
        request_id: str,
        generation_request_id: str,
    ) -> QueueCall[tuple[ExecutionCommand, bool]]:
        return self._scheduler.enqueue(generate_again_command(request_id, generation_request_id))


def process_sku_command(
    batch_id: str,
    request: MarketingCreativeAutomationRequest,
    snapshot_ids: tuple[str, ...],
) -> EnqueueCommand:
    payload = ProcessSkuPayload(
        batch_id=batch_id,
        request=_REQUEST_ADAPTER.dump_python(request, mode="json"),
        snapshot_ids=list(snapshot_ids),
    )
    return EnqueueCommand(
        name=CreativeAutomationCommandName.PROCESS_SKU.value,
        dedupe_key=f"creative-automation:process:{request.request_id}",
        payload=payload.model_dump(mode="json"),
        workflow_run_id=request.request_id,
        max_attempts=3,
    )


def generate_again_command(request_id: str, generation_request_id: str) -> EnqueueCommand:
    payload = GenerateAgainPayload(
        request_id=request_id,
        generation_request_id=generation_request_id,
    )
    return EnqueueCommand(
        name=CreativeAutomationCommandName.GENERATE_AGAIN.value,
        dedupe_key=f"creative-automation:generate-again:{request_id}:{generation_request_id}",
        payload=payload.model_dump(mode="json"),
        workflow_run_id=request_id,
        max_attempts=1,
    )


class CreativeAutomationCommandDispatcher:
    def __init__(
        self,
        execute: Callable[
            [str, MarketingCreativeAutomationRequest, tuple[str, ...]], Awaitable[None]
        ],
        execute_generate_again: Callable[[str, str], Awaitable[None]] | None = None,
        on_failure: Callable[[str, MarketingCreativeAutomationRequest, str], Awaitable[None]]
        | None = None,
        on_retry: Callable[[str, MarketingCreativeAutomationRequest, str], Awaitable[None]]
        | None = None,
    ) -> None:
        self._execute = execute
        self._execute_generate_again = execute_generate_again
        self._on_failure = on_failure
        self._on_retry = on_retry

    async def dispatch(self, command: ExecutionCommand) -> None:
        if command.name == CreativeAutomationCommandName.GENERATE_AGAIN.value:
            if self._execute_generate_again is None:
                raise ValueError("Generate Again command executor is not configured")
            try:
                payload = GenerateAgainPayload.model_validate(command.payload)
                await self._execute_generate_again(
                    payload.request_id,
                    payload.generation_request_id,
                )
            except ValidationError as error:
                raise PermanentCommandError(
                    "INVALID_CREATIVE_AUTOMATION_COMMAND",
                    "Creative automation command payload is invalid",
                ) from error
            except ValueError as error:
                raise PermanentCommandError(
                    "INVALID_CREATIVE_AUTOMATION_STATE", str(error)
                ) from error
            except Exception as error:
                raise TransientCommandError(
                    "CREATIVE_AUTOMATION_SERVICE_ERROR",
                    "Creative automation could not complete an external service call",
                ) from error
            return
        if command.name != CreativeAutomationCommandName.PROCESS_SKU.value:
            raise ValueError(f"Unsupported Creative automation command: {command.name}")
        try:
            payload = ProcessSkuPayload.model_validate(command.payload)
            request = _REQUEST_ADAPTER.validate_python(payload.request)
            await self._execute(payload.batch_id, request, tuple(payload.snapshot_ids))
        except ValidationError as error:
            raise PermanentCommandError(
                "INVALID_CREATIVE_AUTOMATION_COMMAND",
                "Creative automation command payload is invalid",
            ) from error
        except TimeoutError as error:
            code = "CREATIVE_AUTOMATION_TIMEOUT"
            if command.attempts >= command.max_attempts:
                if self._on_failure is not None:
                    await self._on_failure(payload.batch_id, request, code)
            elif self._on_retry is not None:
                await self._on_retry(payload.batch_id, request, code)
            raise TransientCommandError(
                code,
                "Creative automation timed out while calling an external service",
                retry_delay_seconds=_provider_retry_delay_seconds(error),
            ) from error
        except ValueError as error:
            code = "INVALID_CREATIVE_AUTOMATION_STATE"
            logger.opt(exception=error).error(
                "Creative automation command rejected an invalid state: command_id={}, "
                "workflow_run_id={}",
                command.command_id,
                command.workflow_run_id,
            )
            if self._on_failure is not None:
                await self._on_failure(payload.batch_id, request, code)
            raise PermanentCommandError(code, str(error)) from error
        except Exception as error:
            code = "CREATIVE_AUTOMATION_SERVICE_ERROR"
            logger.opt(exception=error).error(
                "Creative automation command failed: command_id={}, workflow_run_id={}, "
                "error_type={}",
                command.command_id,
                command.workflow_run_id,
                type(error).__name__,
            )
            if command.attempts >= command.max_attempts:
                if self._on_failure is not None:
                    await self._on_failure(payload.batch_id, request, code)
            elif self._on_retry is not None:
                await self._on_retry(payload.batch_id, request, code)
            raise TransientCommandError(
                code,
                "Creative automation could not complete an external service call",
                retry_delay_seconds=_provider_retry_delay_seconds(error),
            ) from error


def _provider_retry_delay_seconds(error: BaseException) -> int | None:
    """Keep a durable command off the queue for a provider-requested backoff."""
    match = re.search(
        r"(?:retryDelay|retry in|reset after)[^0-9]{0,64}(\d+(?:\.\d+)?)s",
        str(error),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return max(1, min(math.ceil(float(match.group(1))), 60))


__all__ = [
    "CreativeAutomationCommandDispatcher",
    "CreativeAutomationCommandName",
    "CreativeAutomationCommandService",
    "GenerateAgainPayload",
    "ProcessSkuPayload",
    "generate_again_command",
    "process_sku_command",
]
