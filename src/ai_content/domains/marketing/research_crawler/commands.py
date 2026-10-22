"""Durable execution command for one research crawl job."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_content.platform.execution import (
    EnqueueCommand,
    ExecutionCommand,
    PermanentCommandError,
    TransientCommandError,
)

from .service import ResearchCrawlService


class ResearchCrawlCommandName(StrEnum):
    CRAWL_URL = "research_crawler.crawl_url"


class CrawlUrlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str


def crawl_url_command(job_id: str) -> EnqueueCommand:
    return EnqueueCommand(
        name=ResearchCrawlCommandName.CRAWL_URL.value,
        dedupe_key=f"research-crawl:{job_id}",
        payload=CrawlUrlPayload(job_id=job_id).model_dump(mode="json"),
        workflow_run_id=job_id,
        max_attempts=3,
    )


class ResearchCrawlCommandDispatcher:
    def __init__(self, service: ResearchCrawlService) -> None:
        self._service = service

    async def dispatch(self, command: ExecutionCommand) -> None:
        if command.name != ResearchCrawlCommandName.CRAWL_URL.value:
            raise ValueError(f"Unsupported research crawl command: {command.name}")
        try:
            payload = CrawlUrlPayload.model_validate(command.payload)
        except ValidationError as error:
            raise PermanentCommandError(
                "INVALID_RESEARCH_CRAWL_COMMAND",
                "Research crawl command payload is invalid",
            ) from error
        try:
            await self._service.execute(payload.job_id)
        except ValueError as error:
            await self._service.record_error(
                payload.job_id,
                status="failed",
                code="INVALID_RESEARCH_SOURCE",
                message=str(error),
            )
            raise PermanentCommandError("INVALID_RESEARCH_SOURCE", str(error)) from error
        except Exception as error:
            exhausted = command.attempts >= command.max_attempts
            await self._service.record_error(
                payload.job_id,
                status="failed" if exhausted else "retry_wait",
                code="RESEARCH_CRAWL_FAILED",
                message="The public page could not be fetched",
            )
            raise TransientCommandError(
                "RESEARCH_CRAWL_FAILED",
                "The public page could not be fetched",
            ) from error


__all__ = [
    "CrawlUrlPayload",
    "ResearchCrawlCommandDispatcher",
    "ResearchCrawlCommandName",
    "crawl_url_command",
]
