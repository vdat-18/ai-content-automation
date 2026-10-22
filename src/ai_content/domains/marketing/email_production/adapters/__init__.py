"""Adapters for Email production."""

from .fakes import FixtureEmailGenerator, FixtureSemanticReviewer
from .sqlite_repository import SqliteEmailProductionRepository

__all__ = [
    "FixtureEmailGenerator",
    "FixtureSemanticReviewer",
    "SqliteEmailProductionRepository",
]
