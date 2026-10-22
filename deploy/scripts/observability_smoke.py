"""Bounded smoke checks for the optional observability Compose profile."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from loguru import logger


class ObservabilitySmokeFailure(RuntimeError):
    pass


def _request_json(url: str, authorization: str | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        value = json.loads(response.read())
    return value


def _request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def _wait_for(
    description: str,
    check: Callable[[], bool],
    timeout_seconds: float = 45,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    detail = f": {last_error}" if last_error is not None else ""
    raise ObservabilitySmokeFailure(f"Timed out waiting for {description}{detail}")


def _prometheus_targets_ready(base_url: str) -> bool:
    payload = _request_json(f"{base_url}/api/v1/targets")
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    targets = data.get("activeTargets")
    if not isinstance(targets, list):
        return False
    health_by_job = {
        target.get("labels", {}).get("job"): target.get("health")
        for target in targets
        if isinstance(target, dict) and isinstance(target.get("labels"), dict)
    }
    return all(health_by_job.get(job) == "up" for job in ("aicontent-api", "aicontent-worker"))


def _prometheus_rules_loaded(base_url: str) -> bool:
    payload = _request_json(f"{base_url}/api/v1/rules?type=alert")
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    return isinstance(groups, list) and sum(len(group.get("rules", [])) for group in groups) >= 11


def _tempo_has_api_trace(base_url: str) -> bool:
    tags = urllib.parse.quote("service.name=aicontent-api")
    payload = _request_json(f"{base_url}/api/search?tags={tags}&limit=10")
    if not isinstance(payload, dict):
        return False
    traces = payload.get("traces")
    return isinstance(traces, list) and len(traces) > 0


def _grafana_dashboards_ready(base_url: str, authorization: str) -> bool:
    dashboards = _request_json(f"{base_url}/api/search?tag=aicontent", authorization)
    return isinstance(dashboards, list) and len(dashboards) >= 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the observability profile")
    parser.add_argument("--api-url", default="http://api:8000")
    parser.add_argument("--prometheus-url", default="http://prometheus:9090")
    parser.add_argument("--tempo-url", default="http://tempo:3200")
    parser.add_argument("--grafana-url", default="http://grafana:3000")
    return parser


def main() -> int:
    args = _parser().parse_args()
    username = os.getenv("AIC_GRAFANA_ADMIN_USER", "admin")
    password = os.getenv("AIC_GRAFANA_ADMIN_PASSWORD")
    if not password:
        raise ObservabilitySmokeFailure("Grafana admin password is required")
    authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    api_health = _request_json(f"{args.api_url}/api/v1/health")
    if not isinstance(api_health, dict) or api_health.get("status") != "ok":
        raise ObservabilitySmokeFailure("API did not return a healthy response")
    metrics = _request_text(f"{args.api_url}/internal/metrics/")
    if "aic_ai_requests_total" not in metrics:
        raise ObservabilitySmokeFailure("AI operation metrics were not registered")
    _wait_for(
        "Prometheus API and worker targets", lambda: _prometheus_targets_ready(args.prometheus_url)
    )
    if not _prometheus_rules_loaded(args.prometheus_url):
        raise ObservabilitySmokeFailure("Prometheus alert rules were not loaded")
    _wait_for("an API trace in Tempo", lambda: _tempo_has_api_trace(args.tempo_url))

    grafana_health = _request_json(f"{args.grafana_url}/api/health")
    if not isinstance(grafana_health, dict) or grafana_health.get("database") != "ok":
        raise ObservabilitySmokeFailure("Grafana is not healthy")
    _wait_for(
        "provisioned Grafana dashboards",
        lambda: _grafana_dashboards_ready(args.grafana_url, authorization),
    )
    logger.info("Observability smoke passed: targets, rules, traces and dashboards are ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ObservabilitySmokeFailure as error:
        logger.error("Observability smoke failed: {}", error)
        raise SystemExit(1) from error
