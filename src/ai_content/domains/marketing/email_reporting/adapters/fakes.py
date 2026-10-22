"""Deterministic aggregate sources used by offline Email report fixtures."""

from __future__ import annotations

from ..domain.models import (
    ReportSpecification,
    ReportWindow,
    SnapshotPeriod,
    SourceSnapshot,
    SourceSystem,
)
from ..ports.interfaces import ReportingSourceError


class FixtureReportingSource:
    """Return pinned snapshots without reading a network or customer data."""

    def __init__(self, source: SourceSystem, snapshots: tuple[SourceSnapshot, ...]) -> None:
        self.source = source
        self._snapshots = snapshots
        self.calls: list[tuple[SnapshotPeriod, ReportWindow]] = []

    async def fetch(
        self,
        specification: ReportSpecification,
        period: SnapshotPeriod,
        window: ReportWindow,
    ) -> SourceSnapshot:
        del specification
        self.calls.append((period, window))
        matches = [
            snapshot
            for snapshot in self._snapshots
            if snapshot.source == self.source and snapshot.period == period
        ]
        if len(matches) != 1:
            raise ReportingSourceError(
                f"Expected one {self.source.value}:{period.value} fixture snapshot, "
                f"found {len(matches)}"
            )
        return matches[0]
