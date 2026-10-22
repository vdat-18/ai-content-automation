"""Deterministic fake model adapters for Email production fixtures."""

from __future__ import annotations

from ..domain.models import (
    EmailContextSnapshot,
    EmailPackage,
    EmailTrigger,
    SemanticReview,
)


class FixtureEmailGenerator:
    def __init__(self, packages: tuple[EmailPackage, ...], version: str) -> None:
        if not packages:
            raise ValueError("Fixture generator requires at least one package")
        self._packages = packages
        self._version = version
        self._calls = 0

    @property
    def version(self) -> str:
        return self._version

    async def generate(
        self,
        _trigger: EmailTrigger,
        _context: EmailContextSnapshot,
        _revision_instructions: tuple[str, ...],
    ) -> EmailPackage:
        index = min(self._calls, len(self._packages) - 1)
        self._calls += 1
        return self._packages[index]


class FixtureSemanticReviewer:
    def __init__(self, reviews: tuple[SemanticReview, ...]) -> None:
        if not reviews:
            raise ValueError("Fixture reviewer requires at least one review")
        self._reviews = reviews

    async def review(
        self,
        _package: EmailPackage,
        _context: EmailContextSnapshot,
        version_number: int,
    ) -> SemanticReview:
        return self._reviews[min(version_number - 1, len(self._reviews) - 1)]


__all__ = ["FixtureEmailGenerator", "FixtureSemanticReviewer"]
