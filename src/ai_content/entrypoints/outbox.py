"""Publish transactional execution outbox records to RabbitMQ through Celery."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass
from types import FrameType
from uuid import uuid4

from celery import Celery
from loguru import logger

from ai_content.entrypoints.worker.celery_app import app as celery_app
from ai_content.platform.database import Database
from ai_content.platform.execution import PostgresExecutionOutbox
from ai_content.platform.execution.identifiers import execution_id_for
from ai_content.settings import ApplicationSettings


@dataclass(frozen=True)
class PublishOutcome:
    published: int
    failed: int


class CeleryOutboxPublisher:
    def __init__(
        self,
        outbox: PostgresExecutionOutbox,
        app: Celery,
        publisher_id: str,
        *,
        batch_size: int,
        lease_seconds: int,
        retry_delay_seconds: int,
    ) -> None:
        self._outbox = outbox
        self._app = app
        self._publisher_id = publisher_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def publish_once(self) -> PublishOutcome:
        messages = await self._outbox.claim_batch(
            self._publisher_id,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        published = 0
        failed = 0
        for message in messages:
            try:
                await asyncio.to_thread(
                    self._app.send_task,
                    message.task_name,
                    args=[message.command_id, message.dispatch_generation],
                    task_id=execution_id_for(
                        message.command_id,
                        message.dispatch_generation,
                    ),
                    queue=message.queue_name,
                    retry=False,
                )
            except Exception as error:
                failed += 1
                await self._outbox.release(
                    message.outbox_id,
                    self._publisher_id,
                    str(error),
                    retry_delay_seconds=self._retry_delay_seconds,
                )
                logger.warning(
                    "Outbox publication {} failed on attempt {}",
                    message.outbox_id,
                    message.attempts,
                )
            else:
                published += 1
                await self._outbox.mark_published(message.outbox_id, self._publisher_id)
                logger.info(
                    "Published command {} generation {} to queue {}",
                    message.command_id,
                    message.dispatch_generation,
                    message.queue_name,
                )
        return PublishOutcome(published=published, failed=failed)

    async def run_forever(self, poll_interval_seconds: float, stop_event: asyncio.Event) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("Outbox poll interval must be positive")
        while not stop_event.is_set():
            outcome = await self.publish_once()
            if outcome.published == 0 and outcome.failed == 0:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish execution outbox records")
    parser.add_argument("--once", action="store_true")
    return parser


def _install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown(signal_name: str) -> None:
        logger.info("Outbox publisher shutdown requested by {}", signal_name)
        stop_event.set()

    def fallback_handler(signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(request_shutdown, signal.Signals(signum).name)

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, request_shutdown, shutdown_signal.name)
        except NotImplementedError:
            signal.signal(shutdown_signal, fallback_handler)


async def _async_main(args: argparse.Namespace) -> int:
    settings = ApplicationSettings()
    if settings.database_backend != "postgresql" or settings.database_url is None:
        raise ValueError("Outbox publisher requires PostgreSQL")
    if settings.execution_backend != "celery" or settings.celery_broker_url is None:
        raise ValueError("Outbox publisher requires Celery execution and a broker URL")
    database = Database(settings.database_url.get_secret_value())
    publisher = CeleryOutboxPublisher(
        PostgresExecutionOutbox(database.engine),
        celery_app,
        f"outbox-{uuid4()}",
        batch_size=settings.outbox_batch_size,
        lease_seconds=settings.outbox_lease_seconds,
        retry_delay_seconds=settings.outbox_retry_delay_seconds,
    )
    try:
        if args.once:
            outcome = await publisher.publish_once()
            logger.info(
                "Outbox pass completed: published={} failed={}",
                outcome.published,
                outcome.failed,
            )
            return 0
        stop_event = asyncio.Event()
        _install_shutdown_handlers(stop_event)
        await publisher.run_forever(settings.outbox_poll_interval_seconds, stop_event)
        return 0
    finally:
        await database.close()
        celery_app.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CeleryOutboxPublisher", "PublishOutcome", "main"]
