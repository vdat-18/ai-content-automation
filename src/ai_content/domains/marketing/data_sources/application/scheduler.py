"""Recurring background synchronization for configured data sources."""

from __future__ import annotations

import asyncio

from loguru import logger

from ai_content.platform.execution import CommandScheduler

from ..commands import enqueue_data_source_sync


async def run_data_source_sync_schedule(
    queue: CommandScheduler,
    source_ids: tuple[str, ...],
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Periodically enqueue one durable sync command without overlapping runs."""
    while not stop_event.is_set():
        try:
            command, created = await enqueue_data_source_sync(queue, source_ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled data source sync failed to enqueue")
        else:
            logger.info(
                "Scheduled data source sync {} as command {} for {} sources",
                "enqueued" if created else "already active",
                command.command_id,
                len(source_ids),
            )
        try:
            # Returns as soon as the stop event fires, TimeoutError otherwise.
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            break
        except TimeoutError:
            pass


__all__ = ["run_data_source_sync_schedule"]
