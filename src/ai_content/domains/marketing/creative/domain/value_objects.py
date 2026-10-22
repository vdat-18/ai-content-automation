"""Value objects for Creative subdomain."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class GenerationBudget:
    """Budget constraints for generation."""

    max_retries: int = 3
    max_cost: Decimal | None = None

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.max_cost is not None and self.max_cost < 0:
            raise ValueError("max_cost cannot be negative")

    def allows_retry(self, current_retries: int, current_cost: Decimal) -> bool:
        """Check if retry is allowed within budget."""
        if current_retries >= self.max_retries:
            return False
        return self.max_cost is None or current_cost < self.max_cost

    def allows_generation(self, current_cost: Decimal) -> bool:
        """Check if generation is allowed (check before generation)."""
        return self.max_cost is None or current_cost < self.max_cost

    def is_cost_exceeded(self, current_cost: Decimal) -> bool:
        """Check if cost limit is exceeded."""
        if self.max_cost is None:
            return False
        return current_cost > self.max_cost


@dataclass(frozen=True)
class QAResult:
    """Result of QA check on an asset version."""

    passed: bool
    score: Decimal
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    feedback: str | None = None
    rubric_version: str | None = None

    def __post_init__(self) -> None:
        if self.score < 0 or self.score > 100:
            raise ValueError("Score must be between 0 and 100")

    @classmethod
    def pass_result(
        cls,
        score: Decimal,
        warnings: tuple[str, ...] = (),
        rubric_version: str | None = None,
    ) -> QAResult:
        return cls(passed=True, score=score, warnings=warnings, rubric_version=rubric_version)

    @classmethod
    def fail_result(
        cls,
        score: Decimal,
        issues: tuple[str, ...],
        feedback: str | None = None,
        warnings: tuple[str, ...] = (),
        rubric_version: str | None = None,
    ) -> QAResult:
        return cls(
            passed=False,
            score=score,
            issues=issues,
            feedback=feedback,
            warnings=warnings,
            rubric_version=rubric_version,
        )


__all__ = [
    "GenerationBudget",
    "QAResult",
]
