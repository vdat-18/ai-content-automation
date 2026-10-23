"""CLI for enqueueing and executing persistent local workflow commands."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import FrameType
from uuid import uuid4

from loguru import logger

from ai_content.domains.marketing.creative.adapters.model_readiness import (
    probe_preparation_model,
)
from ai_content.domains.marketing.creative.config.preparation import load_preparation_config
from ai_content.domains.marketing.creative_feedback.config.learning import (
    load_performance_learning_config,
)
from ai_content.domains.marketing.creative_loop.adapters.commands import (
    CreativeLoopCommandDispatcher,
    CreativeLoopCommandService,
)
from ai_content.domains.marketing.creative_loop.bootstrap import CreativeLoopRuntime
from ai_content.domains.marketing.creative_loop.config.fixtures import (
    load_creative_loop_fixture,
)
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.database import Database
from ai_content.platform.execution import (
    CommandQueue,
    CommandScheduler,
    CommandStatus,
    ExecutionWorker,
    SqliteCommandQueue,
    resolve_queue_call,
)
from ai_content.platform.observability import (
    configure_observability,
    instrument_sqlalchemy,
    sample_commands_forever,
    start_worker_metrics_server,
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

    enqueue = subparsers.add_parser("enqueue", help="Enqueue one synthetic Creative loop case")
    enqueue.add_argument("--case-id", required=True)

    run = subparsers.add_parser("run", help="Run queued workflow commands")
    run.add_argument("--once", action="store_true")
    run.add_argument("--poll-interval", type=float, default=1.0)
    run.add_argument("--lease-seconds", type=int, default=60)

    listing = subparsers.add_parser("list", help="List execution commands")
    listing.add_argument("--status", choices=[item.value for item in CommandStatus])

    retry = subparsers.add_parser("retry", help="Retry one failed command")
    retry.add_argument("--command-id", required=True)
    return parser


def _data_root(value: Path | None, settings: ApplicationSettings) -> Path:
    if value is not None:
        return value
    return settings.data_root


def _install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    """Translate process termination signals into a graceful worker stop."""
    loop = asyncio.get_running_loop()

    def request_shutdown(signal_name: str) -> None:
        logger.info("Worker shutdown requested by {}", signal_name)
        stop_event.set()

    def fallback_handler(signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(request_shutdown, signal.Signals(signum).name)

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                shutdown_signal,
                request_shutdown,
                shutdown_signal.name,
            )
        except NotImplementedError:
            signal.signal(shutdown_signal, fallback_handler)


async def _run_worker(
    args: argparse.Namespace,
    queue: CommandQueue,
    root: Path,
    settings: ApplicationSettings,
    preparation_api_key: str | None,
    runtime_factory: Callable[[], CreativeLoopRuntime] | None = None,
) -> int:
    dispatcher = CreativeLoopCommandDispatcher(
        root / "state.db",
        root / "artifacts",
        args.config,
        args.config / "fixtures/creative_loop_synthetic.json",
        settings.preparation_config_path,
        preparation_api_key,
        runtime_factory=runtime_factory,
    )
    worker = ExecutionWorker(
        queue,
        dispatcher,
        worker_id=f"local-worker-{uuid4()}",
        lease_seconds=args.lease_seconds,
    )
    if args.once:
        outcome = await worker.run_once()
        if outcome is None:
            logger.info("No execution command is ready")
        else:
            logger.info("Command {} finished with {}", outcome.command_id, outcome.status.value)
        return 0
    stop_event = asyncio.Event()
    _install_shutdown_handlers(stop_event)
    await worker.run_forever(args.poll_interval, stop_event=stop_event)
    logger.info("Worker stopped cleanly")
    return 0


async def _async_main(args: argparse.Namespace, settings: ApplicationSettings) -> int:
    root = _data_root(args.data_root, settings)
    observability_settings = settings.observability("aicontent-worker")
    observability_runtime = configure_observability(observability_settings)
    backend = settings.database_backend
    database = None
    runtime_factory = None
    preparation_settings = load_preparation_config(settings.preparation_config_path)
    preparation_api_key = settings.credential(preparation_settings.api_key_env)
    if args.command == "run":
        await probe_preparation_model(preparation_settings, preparation_api_key)
        if preparation_settings.backend == "baml" and preparation_settings.probe_on_startup:
            logger.info(
                "Preparation model route is ready: backend={} model={}",
                preparation_settings.backend,
                preparation_settings.model,
            )
    if backend == "postgresql":
        assert settings.database_url is not None
        database_url = settings.database_url.get_secret_value()
        database = Database(database_url)
        instrument_sqlalchemy(database.engine, observability_settings)
        execution_backend = settings.execution_backend
        storage_settings = settings.object_storage()
        learning_settings = (
            load_performance_learning_config(settings.learning_config)
            if settings.learning_config
            else None
        )
        container = PostgresRuntimeContainer(
            database,
            root / "artifacts",
            args.config,
            preparation_config_path=settings.preparation_config_path,
            preparation_api_key=preparation_api_key,
            learning_config_path=settings.learning_config,
            learning_api_key=(
                settings.credential(learning_settings.api_key_env)
                if learning_settings is not None
                else None
            ),
            execution_backend=execution_backend,
            object_storage=storage_settings.build() if storage_settings.backend == "s3" else None,
            object_storage_bucket=storage_settings.bucket,
        )
        queue: CommandScheduler = container.execution_scheduler
        runtime_factory = container.creative_loop
    elif backend == "sqlite":
        queue = SqliteCommandQueue(root / "state.db")
    else:
        raise ValueError("AIC_AI_DATABASE_BACKEND must be sqlite or postgresql")
    metrics_server = None
    metrics_stop = asyncio.Event()
    metrics_task: asyncio.Task[None] | None = None
    if args.command == "run" and observability_settings.metrics_enabled:
        metrics_server = start_worker_metrics_server(observability_settings.metrics_port)
        if database is not None:
            metrics_task = asyncio.create_task(
                sample_commands_forever(
                    container.execution_status_store,
                    metrics_stop,
                    observability_settings.command_metrics_interval_seconds,
                )
            )
    try:
        if args.command == "enqueue":
            fixture = load_creative_loop_fixture(
                args.config / "fixtures/creative_loop_synthetic.json"
            )
            command, created = await resolve_queue_call(
                CreativeLoopCommandService(queue).enqueue_start(fixture.case(args.case_id))
            )
            logger.info(
                "Execution command {} {}",
                command.command_id,
                "enqueued" if created else "already exists",
            )
            return 0
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
        if backend == "postgresql" and execution_backend == "celery":
            raise ValueError(
                "Celery execution must run through the Celery worker entrypoint, not worker run"
            )
        return await _run_worker(
            args,
            queue,
            root,
            settings,
            preparation_api_key,
            runtime_factory,
        )
    finally:
        metrics_stop.set()
        if metrics_task is not None:
            with suppress(asyncio.CancelledError):
                await metrics_task
        if metrics_server is not None:
            server, thread = metrics_server
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
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
