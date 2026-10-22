"""Ports used by the Email Marketing reporting application."""

from .interfaces import IEmailReportingSource, IEmailReportRepository, ReportingSourceError

__all__ = ["IEmailReportRepository", "IEmailReportingSource", "ReportingSourceError"]
