"""Adapter exports for the Email reporting pilot."""

from .fakes import FixtureReportingSource
from .sqlite_repository import SqliteEmailReportRepository

__all__ = ["FixtureReportingSource", "SqliteEmailReportRepository"]
