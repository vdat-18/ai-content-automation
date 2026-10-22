"""External boundaries for read-only Email Marketing reporting."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import (
    EmailPerformanceReport,
    ReportSpecification,
    ReportWindow,
    SnapshotPeriod,
    SourceSnapshot,
)


class ReportingSourceError(Exception):
    """Expected failure while reading an aggregate reporting source."""


class IEmailReportingSource(Protocol):
    async def fetch(
        self,
        specification: ReportSpecification,
        period: SnapshotPeriod,
        window: ReportWindow,
    ) -> SourceSnapshot: ...


class IEmailReportRepository(Protocol):
    async def save(self, report: EmailPerformanceReport) -> None: ...

    async def get(self, report_id: str) -> EmailPerformanceReport | None: ...

    async def get_by_source_run_id(self, source_run_id: str) -> EmailPerformanceReport | None: ...

    async def list(self) -> list[EmailPerformanceReport]: ...
