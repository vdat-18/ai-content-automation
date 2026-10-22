"""Pure reporting projections shared by AI usage persistence adapters."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from .models import AIUsageCost, AIUsageEvent, AIUsageRun


def build_usage_runs(events: Iterable[AIUsageEvent]) -> tuple[AIUsageRun, ...]:
    """Group provider calls by their persisted run identity without inventing lineage."""
    grouped: dict[str, list[AIUsageEvent]] = defaultdict(list)
    for event in events:
        if event.run_id is not None:
            grouped[event.run_id].append(event)

    runs = [_run(run_id, records) for run_id, records in grouped.items()]
    return tuple(sorted(runs, key=lambda item: item.started_at, reverse=True))


def percentile_duration(values: Iterable[int], percentile: float) -> int | None:
    """Return a linear-interpolated percentile for the reported call durations."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _run(run_id: str, events: list[AIUsageEvent]) -> AIUsageRun:
    ordered = sorted(events, key=lambda item: item.started_at)
    costs: dict[str, Decimal] = defaultdict(Decimal)
    for event in ordered:
        if event.cost_amount is not None and event.cost_currency is not None:
            costs[event.cost_currency] += event.cost_amount
    incomplete = sum(event.status == "started" for event in ordered)
    failed = sum(event.status == "failed" for event in ordered)
    succeeded = sum(event.status == "succeeded" for event in ordered)
    return AIUsageRun(
        run_id=run_id,
        batch_id=_single_value(event.batch_id for event in ordered),
        brand_id=_single_value(event.brand_id for event in ordered),
        status=_run_status(succeeded, failed, incomplete),
        attempts=len(ordered),
        succeeded=succeeded,
        failed=failed,
        incomplete=incomplete,
        input_tokens=sum(event.input_tokens or 0 for event in ordered),
        output_tokens=sum(event.output_tokens or 0 for event in ordered),
        output_count=sum(event.output_count or 0 for event in ordered),
        output_bytes=sum(event.output_bytes or 0 for event in ordered),
        total_duration_ms=sum(event.duration_ms or 0 for event in ordered),
        costs=tuple(AIUsageCost(currency, amount) for currency, amount in sorted(costs.items())),
        models=tuple(sorted({event.model for event in ordered})),
        operations=tuple(sorted({event.operation for event in ordered})),
        started_at=ordered[0].started_at,
        completed_at=max(
            (event.completed_at for event in ordered if event.completed_at is not None),
            default=None,
        ),
    )


def _single_value(values: Iterable[str | None]) -> str | None:
    found = {value for value in values if value is not None}
    return next(iter(found)) if len(found) == 1 else None


def _run_status(succeeded: int, failed: int, incomplete: int) -> str:
    if incomplete:
        return "running"
    if failed and succeeded:
        return "attention"
    if failed:
        return "failed"
    return "succeeded"


__all__ = ["build_usage_runs", "percentile_duration"]
