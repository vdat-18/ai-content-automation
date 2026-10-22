"""Load the executable subset of a Static Creative review rubric."""

from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

import yaml

from ..domain.reviews import ReviewRubric, RubricCriterion
from .loader import ConfigError


def load_review_rubric(path: Path) -> ReviewRubric:
    """Load scoring and gate definitions from one versioned rubric file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Rubric must be a YAML mapping: {path}")
    try:
        policy = _mapping(raw["candidate_decision_policy"], "candidate_decision_policy")
        approval = _mapping(policy["approval_ready"], "approval_ready")
        revise = _mapping(policy["revise"], "revise")
        reject = _mapping(policy["reject"], "reject")
        revise_range = revise["weighted_score_range"]
        if not isinstance(revise_range, list | tuple) or len(revise_range) != 2:
            raise ValueError("revise.weighted_score_range must contain two values")
        rubric = ReviewRubric(
            rubric_id=str(raw["id"]),
            version=str(raw["version"]),
            hard_gates=tuple(
                RubricCriterion(str(_mapping(item, "hard_gate")["id"]))
                for item in _list(raw["hard_gates"], "hard_gates")
            ),
            scored_criteria=tuple(
                RubricCriterion(
                    str(_mapping(item, "scored_criterion")["id"]),
                    Decimal(str(_mapping(item, "scored_criterion")["weight"])),
                )
                for item in _list(raw["scored_criteria"], "scored_criteria")
            ),
            set_gates=tuple(
                RubricCriterion(str(_mapping(item, "set_gate")["id"]))
                for item in _list(raw.get("set_gates", []), "set_gates")
            ),
            approval_ready_score=Decimal(str(approval["minimum_weighted_score"])),
            revise_min_score=Decimal(str(revise_range[0])),
            revise_max_score=Decimal(str(revise_range[1])),
            reject_max_score=Decimal(str(reject["maximum_weighted_score"])),
        )
    except (DecimalException, KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid executable rubric in {path}: {exc}") from exc
    return rubric


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


__all__ = ["load_review_rubric"]
