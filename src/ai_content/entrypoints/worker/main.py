"""CLI for enqueueing and executing persistent local workflow commands."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from ai_content.domains.marketing.creative.config.preparation import PreparationConfig
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.database import Database
from ai_content.platform.execution import (
    CommandScheduler,
    CommandStatus,
    SqliteCommandQueue,
    resolve_queue_call,
)
from ai_content.platform.observability import (
    configure_observability,
    instrument_sqlalchemy,
)
from ai_content.settings import ApplicationSettings


def _parser(config_dir: Path = Path("config")) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local persistent execution pilot")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--config",
        type=Path,
        default=config_dir,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="List execution commands")
    listing.add_argument("--status", choices=[item.value for item in CommandStatus])

    retry = subparsers.add_parser("retry", help="Retry one failed command")
    retry.add_argument("--command-id", required=True)
    return parser


def _data_root(value: Path | None, settings: ApplicationSettings) -> Path:
    if value is not None:
        return value
    return settings.data_root


async def _async_main(args: argparse.Namespace, settings: ApplicationSettings) -> int:
    root = _data_root(args.data_root, settings)
    observability_settings = settings.observability("aicontent-worker")
    observability_runtime = configure_observability(observability_settings)
    backend = settings.database_backend
    database = None
    preparation_settings = PreparationConfig.from_settings(settings)
    preparation_api_key = preparation_settings.api_key
    if backend == "postgresql":
        assert settings.database_url is not None
        database_url = settings.database_url.get_secret_value()
        database = Database(database_url)
        instrument_sqlalchemy(database.engine, observability_settings)
        execution_backend = settings.execution_backend
        storage_settings = settings.object_storage()
        container = PostgresRuntimeContainer(
            database,
            root / "artifacts",
            args.config,
            preparation_config=preparation_settings,
            preparation_api_key=preparation_api_key,
            execution_backend=execution_backend,
            object_storage=storage_settings.build() if storage_settings.backend == "s3" else None,
            object_storage_bucket=storage_settings.bucket,
        )
        queue: CommandScheduler = container.execution_scheduler
    elif backend == "sqlite":
        queue = SqliteCommandQueue(root / "state.db")
    else:
        raise ValueError("AIC_AI_DATABASE_BACKEND must be sqlite or postgresql")
    try:
        if args.command == "list":
            status = CommandStatus(args.status) if args.status else None
            commands = await resolve_queue_call(queue.list(status=status))
            for command in commands:
                logger.info(
                    "{} {} {} attempts={}/{}",
                    command.command_id,
                    command.name,
                    command.status.value,
                    command.attempts,
                    command.max_attempts,
                )
            return 0
        if args.command == "retry":
            command = await resolve_queue_call(queue.retry_failed(args.command_id))
            logger.info("Execution command {} queued for manual retry", command.command_id)
            return 0
        raise ValueError(f"Unsupported command: {args.command}")
    finally:
        queue.close()
        if database is not None:
            await database.close()
        observability_runtime.shutdown()


def main(argv: list[str] | None = None) -> int:
    settings = ApplicationSettings()
    args = _parser(settings.config_dir).parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_async_main(args, settings))


__all__ = ["main"]
