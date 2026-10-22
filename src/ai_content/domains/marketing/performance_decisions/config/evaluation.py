"""Versioned evaluation suite for Creative Opportunity analysis."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.models import EvaluationState, OpportunityCategory


class OpportunityEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    expected_data_quality: EvaluationState
    allowed_categories: tuple[OpportunityCategory, ...] = Field(min_length=1)


class OpportunityEvaluationRubric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required: tuple[str, ...] = Field(min_length=1)


class OpportunityEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: tuple[OpportunityEvaluationCase, ...] = Field(min_length=1)
    rubric: OpportunityEvaluationRubric

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> "OpportunityEvaluationSuite":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")
        return self


def load_opportunity_evaluation_suite(path: Path) -> OpportunityEvaluationSuite:
    return OpportunityEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "OpportunityEvaluationCase",
    "OpportunityEvaluationRubric",
    "OpportunityEvaluationSuite",
    "load_opportunity_evaluation_suite",
]
