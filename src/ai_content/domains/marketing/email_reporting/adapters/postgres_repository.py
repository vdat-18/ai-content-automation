"""PostgreSQL persistence for Email reports."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import email_reports

from ..domain.models import EmailPerformanceReport
from .serialization import report_from_dict, report_to_dict


class PostgresEmailReportRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, email_reports, report_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, report: EmailPerformanceReport) -> None:
        await self._store.insert(
            {
                "report_id": report.report_id,
                "source_run_id": report.specification.source_run_id,
                "status": report.status.value,
                "payload": report_to_dict(report),
            }
        )

    async def get(self, report_id: str) -> EmailPerformanceReport | None:
        return await self._store.get(email_reports.c.report_id, report_id)

    async def get_by_source_run_id(self, source_run_id: str) -> EmailPerformanceReport | None:
        return await self._store.get(email_reports.c.source_run_id, source_run_id)

    async def list(self) -> list[EmailPerformanceReport]:
        return await self._store.list()


__all__ = ["PostgresEmailReportRepository"]
