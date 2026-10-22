"""Idempotent HTTP smoke test for the Dockerized synthetic Creative loop."""

from __future__ import annotations

import argparse
import json
import time
from http.client import HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from loguru import logger


class SmokeFailure(RuntimeError):
    """Raised when a required Docker smoke contract is not satisfied."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://frontend:8080")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def _open(request: Request, timeout: float = 5.0) -> HTTPResponse:
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as error:
        detail = error.read(500).decode("utf-8", errors="replace")
        raise SmokeFailure(f"HTTP {error.code} from {request.full_url}: {detail}") from error
    except URLError as error:
        raise SmokeFailure(f"Could not reach {request.full_url}") from error


def _request_bytes(base_url: str, path: str) -> bytes:
    with _open(Request(f"{base_url.rstrip('/')}{path}")) as response:
        if response.status != 200:
            raise SmokeFailure(f"Expected HTTP 200 from {path}, received {response.status}")
        return response.read()


def _verify_exact_artifact_range(base_url: str, artifact_id: str) -> None:
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/artifacts/{quote(artifact_id, safe='')}/content",
        headers={"Range": "bytes=0-9"},
    )
    with _open(request) as response:
        if response.status != 206:
            raise SmokeFailure("Exact artifact endpoint did not return HTTP 206")
        if len(response.read()) != 10:
            raise SmokeFailure("Exact artifact endpoint returned the wrong byte range")
        if not response.headers.get("Content-Range", "").startswith("bytes 0-9/"):
            raise SmokeFailure("Exact artifact endpoint omitted its Content-Range")


def _request_json(
    base_url: str,
    path: str,
    method: str = "GET",
    body: dict[str, object] | None = None,
) -> object:
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if encoded is not None else {}
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=encoded,
        headers=headers,
        method=method,
    )
    with _open(request) as response:
        return json.loads(response.read())


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SmokeFailure(f"{context} did not return a JSON object")
    return value


def _list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise SmokeFailure(f"{context} did not return a JSON list")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SmokeFailure(f"{context} did not return a non-empty string")
    return value


def _wait_until_ready(base_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = _mapping(_request_json(base_url, "/health/ready"), "readiness")
            if response.get("status") == "ok":
                return
        except SmokeFailure:
            pass
        time.sleep(0.5)
    raise SmokeFailure("Synthetic stack did not become ready before the timeout")


def _wait_for_command(base_url: str, command_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    path = f"/api/v1/execution/commands/{quote(command_id, safe='')}"
    while time.monotonic() < deadline:
        command = _mapping(_request_json(base_url, path), "execution command")
        command_status = command.get("status")
        if command_status == "completed":
            return
        if command_status == "failed":
            error_code = command.get("last_error_code") or "UNKNOWN"
            raise SmokeFailure(f"Synthetic command failed with {error_code}")
        time.sleep(0.5)
    raise SmokeFailure("Synthetic command did not complete before the timeout")


def _find_single_item(
    items: object,
    key: str,
    expected: str,
    context: str,
) -> dict[str, object]:
    matches = []
    for raw_item in _list(items, context):
        item = _mapping(raw_item, context)
        if item.get(key) == expected:
            matches.append(item)
    if len(matches) != 1:
        raise SmokeFailure(f"Expected one {context} for {key}={expected}, found {len(matches)}")
    return matches[0]


def run_smoke(base_url: str, timeout: float) -> None:
    if timeout <= 0:
        raise SmokeFailure("Smoke timeout must be positive")

    _wait_until_ready(base_url, timeout)
    live = _mapping(_request_json(base_url, "/health/live"), "liveness")
    if live.get("status") != "ok":
        raise SmokeFailure("Liveness endpoint is not healthy")

    dashboard_html = _request_bytes(base_url, "/dashboard/")
    if b'<div id="root"></div>' not in dashboard_html:
        raise SmokeFailure("Dashboard HTML does not contain the React root")

    accepted = _mapping(
        _request_json(
            base_url,
            "/api/v1/marketing/creative-loops/commands/start",
            method="POST",
            body={"input_snapshot_id": "creative-loop-happy-path"},
        ),
        "start command",
    )
    command = _mapping(accepted.get("command"), "start command payload")
    command_id = _string(command.get("command_id"), "start command ID")
    _wait_for_command(base_url, command_id, timeout)

    loops = _mapping(
        _request_json(base_url, "/api/v1/marketing/creative-loops"),
        "Creative loop list",
    )
    creative_loop = _find_single_item(
        loops.get("items"),
        "input_snapshot_id",
        "creative-loop-happy-path",
        "Creative loop",
    )
    if creative_loop.get("state") != "awaiting_demand_approval":
        raise SmokeFailure("Creative loop did not stop at the demand approval gate")
    run_id = _string(creative_loop.get("run_id"), "Creative loop run ID")
    source_run_id = _string(creative_loop.get("source_run_id"), "Creative loop source run ID")

    snapshot = _mapping(
        _request_json(base_url, "/api/v1/dashboard/snapshot"),
        "Dashboard snapshot",
    )
    _find_single_item(snapshot.get("workflows"), "entity_id", run_id, "Dashboard workflow")

    artifact_path = f"/artifacts/creative-loops/{quote(source_run_id, safe='')}/manifest.json"
    with _open(Request(f"{base_url.rstrip('/')}{artifact_path}")) as response:
        if response.status != 200:
            raise SmokeFailure("Creative loop artifact compatibility route failed")
        artifact_id = response.headers.get("X-Artifact-ID")
        artifact = _mapping(json.loads(response.read()), "Creative loop artifact")
    if artifact.get("run_id") != run_id:
        raise SmokeFailure("Creative loop artifact does not match the persisted workflow")
    if not artifact_id:
        raise SmokeFailure("Creative loop artifact is not backed by the artifact catalog")
    metadata = _mapping(
        _request_json(base_url, f"/api/v1/artifacts/{quote(artifact_id, safe='')}"),
        "Artifact metadata",
    )
    if metadata.get("status") != "available" or metadata.get("artifact_id") != artifact_id:
        raise SmokeFailure("Artifact metadata does not identify an available exact object")
    _verify_exact_artifact_range(base_url, artifact_id)

    logger.info(
        "Docker smoke passed for command {} and workflow {}",
        command_id,
        run_id,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        run_smoke(args.base_url, args.timeout)
    except SmokeFailure as error:
        logger.error("Docker smoke failed: {}", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
