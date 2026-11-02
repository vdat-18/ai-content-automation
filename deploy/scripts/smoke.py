"""Idempotent HTTP smoke test for the Dockerized stack."""

from __future__ import annotations

import argparse
import json
import time
from http.client import HTTPResponse
from urllib.error import HTTPError, URLError
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
    raise SmokeFailure("Stack did not become ready before the timeout")


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

    logger.info("Docker smoke passed for {}", base_url)


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
