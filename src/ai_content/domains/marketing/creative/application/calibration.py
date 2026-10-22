"""Pure calibration metrics comparing automated and human review labels."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.reviews import CriterionStatus, ReviewOutcome


@dataclass(frozen=True)
class CalibrationExample:
    sample_id: str
    automated_outcome: ReviewOutcome
    human_accepted: bool
    automated_criteria: tuple[tuple[str, CriterionStatus], ...] = ()
    human_criteria: tuple[tuple[str, CriterionStatus], ...] = ()


@dataclass(frozen=True)
class CriterionAgreement:
    compared: int
    agreed: int

    @property
    def agreement_rate(self) -> float | None:
        return self.agreed / self.compared if self.compared else None


@dataclass(frozen=True)
class CalibrationReport:
    samples: int
    agreed: int
    false_accepts: int
    false_rejects: int
    unknowns: int
    criterion_agreement: tuple[tuple[str, CriterionAgreement], ...]

    @property
    def agreement_rate(self) -> float | None:
        return self.agreed / self.samples if self.samples else None

    @property
    def false_accept_rate(self) -> float | None:
        return self.false_accepts / self.samples if self.samples else None

    @property
    def false_reject_rate(self) -> float | None:
        return self.false_rejects / self.samples if self.samples else None

    @property
    def unknown_rate(self) -> float | None:
        return self.unknowns / self.samples if self.samples else None


def calculate_calibration(examples: tuple[CalibrationExample, ...]) -> CalibrationReport:
    """Calculate conservative agreement metrics without treating UNKNOWN as PASS."""
    sample_ids = [item.sample_id for item in examples]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("Calibration sample_id values must be unique")

    agreed = 0
    false_accepts = 0
    false_rejects = 0
    unknowns = 0
    criterion_counts: dict[str, list[int]] = {}
    for item in examples:
        automated_accept = item.automated_outcome == ReviewOutcome.PASS
        if item.automated_outcome == ReviewOutcome.UNKNOWN:
            unknowns += 1
        elif automated_accept == item.human_accepted:
            agreed += 1
        elif automated_accept:
            false_accepts += 1
        else:
            false_rejects += 1

        automated = dict(item.automated_criteria)
        human = dict(item.human_criteria)
        if len(automated) != len(item.automated_criteria) or len(human) != len(item.human_criteria):
            raise ValueError("Criterion IDs must be unique within each calibration sample")
        for criterion_id in automated.keys() & human.keys():
            counts = criterion_counts.setdefault(criterion_id, [0, 0])
            counts[0] += 1
            counts[1] += automated[criterion_id] == human[criterion_id]

    return CalibrationReport(
        samples=len(examples),
        agreed=agreed,
        false_accepts=false_accepts,
        false_rejects=false_rejects,
        unknowns=unknowns,
        criterion_agreement=tuple(
            (criterion_id, CriterionAgreement(compared=counts[0], agreed=counts[1]))
            for criterion_id, counts in sorted(criterion_counts.items())
        ),
    )


__all__ = [
    "CalibrationExample",
    "CalibrationReport",
    "CriterionAgreement",
    "calculate_calibration",
]
