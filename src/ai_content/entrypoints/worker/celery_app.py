"""Celery application for durable execution commands."""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import (
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutdown,
)
from loguru import logger
from prometheus_client import multiprocess

from ai_content.platform.observability import (
    configure_observability,
    start_worker_metrics_server,
)
from ai_content.settings import ApplicationSettings

from ...platform.execution import CELERY_CONTROL_QUEUE, CELERY_EXECUTE_COMMAND_TASK

settings = ApplicationSettings()
broker_url = (
    settings.celery_broker_url.get_secret_value()
    if settings.celery_broker_url is not None
    else "amqp://guest:guest@127.0.0.1:5672//"
)

app = Celery("ai-content-automation", broker=broker_url)
app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=settings.celery_broker_connection_timeout_seconds,
    broker_transport_options={"confirm_publish": True},
    task_acks_late=True,
    task_default_queue=CELERY_CONTROL_QUEUE,
    task_ignore_result=True,
    task_publish_retry=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_prefetch_multiplier=1,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_routes={CELERY_EXECUTE_COMMAND_TASK: {"queue": CELERY_CONTROL_QUEUE}},
)

_observability_runtime = None
_process_observability_runtime = None
_metrics_server = None


@worker_process_init.connect
def _start_worker_process_runtime(**_kwargs) -> None:
    global _process_observability_runtime
    _process_observability_runtime = configure_observability(
        settings.observability("aicontent-worker")
    )


@worker_process_shutdown.connect
def _stop_worker_process_runtime(pid: int | None = None, **_kwargs) -> None:
    global _process_observability_runtime
    if _process_observability_runtime is not None:
        _process_observability_runtime.shutdown()
        _process_observability_runtime = None
    if pid is not None and os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        try:
            multiprocess.mark_process_dead(pid)
        except OSError as error:
            logger.warning("Could not finalize worker metrics for process {}: {}", pid, error)


@worker_ready.connect
def _start_worker_runtime(**_kwargs) -> None:
    global _metrics_server, _observability_runtime
    observability = settings.observability("aicontent-worker")
    _observability_runtime = configure_observability(observability)
    if observability.metrics_enabled:
        _metrics_server = start_worker_metrics_server(observability.metrics_port)


@worker_shutdown.connect
def _stop_worker_runtime(**_kwargs) -> None:
    global _metrics_server, _observability_runtime
    if _metrics_server is not None:
        server, thread = _metrics_server
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _metrics_server = None
    if _observability_runtime is not None:
        _observability_runtime.shutdown()
        _observability_runtime = None


from . import celery_tasks as _celery_tasks  # noqa: E402,F401

__all__ = ["app"]
