"""Non-destructive observability drills for local or staging environments."""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime, timedelta

from loguru import logger


class DrillFailure(RuntimeError):
    pass


def _post_json(url: str, payload: object) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status not in {200, 202}:
            raise DrillFailure(f"Alertmanager returned HTTP {response.status}")


def alert_delivery(alertmanager_url: str, execute: bool) -> None:
    """Submit a bounded synthetic alert that resolves automatically."""
    if not execute:
        logger.info(
            "Dry run: would submit AicControlledObservabilityDrill to {}",
            alertmanager_url,
        )
        return
    now = datetime.now(UTC)
    payload = [
        {
            "labels": {
                "alertname": "AicControlledObservabilityDrill",
                "severity": "warning",
                "owner": "marketing-ai-operations",
                "component": "observability",
                "drill": "true",
            },
            "annotations": {
                "summary": "Controlled observability drill",
                "description": "Synthetic alert used to verify routing and acknowledgement.",
                "runbook_url": "docs/runbooks/CONTROLLED_DRILLS.md",
            },
            "startsAt": now.isoformat(),
            "endsAt": (now + timedelta(minutes=5)).isoformat(),
            "generatorURL": "aicontent://observability-drill",
        }
    ]
    _post_json(f"{alertmanager_url.rstrip('/')}/api/v2/alerts", payload)
    logger.info("Controlled alert submitted; verify receipt and automatic resolution")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded observability drill")
    parser.add_argument("scenario", choices=("alert-delivery",))
    parser.add_argument("--alertmanager-url", default="http://alertmanager:9093")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Submit the synthetic alert; omission performs a dry run.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.scenario == "alert-delivery":
        alert_delivery(args.alertmanager_url, args.execute)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DrillFailure, OSError) as error:
        logger.error("Observability drill failed: {}", error)
        raise SystemExit(1) from error
