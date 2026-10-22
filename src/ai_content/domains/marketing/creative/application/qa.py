"""Compose deterministic technical checks with model-agnostic semantic review."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ..domain.entities import QACheckResult, QASession
from ..domain.reviews import RepairAction, ReviewOutcome
from ..ports.interfaces import IQAChecker, ISemanticReviewer, SemanticReviewError


class CompositeCreativeQAChecker:
    """Short-circuit technical failures before running semantic review."""

    def __init__(
        self,
        technical_checker: IQAChecker,
        semantic_reviewer: ISemanticReviewer,
    ) -> None:
        self._technical_checker = technical_checker
        self._semantic_reviewer = semantic_reviewer

    async def check(self, session: QASession) -> QACheckResult:
        technical = await self._technical_checker.check(session)
        if not technical.passed:
            return technical

        semantic = await self._semantic_reviewer.review(session)
        evidence_refs = tuple(item.evidence_id for item in semantic.evidence)
        repair_actions = tuple(dict.fromkeys(issue.repair_action for issue in semantic.issues))
        issue_codes = tuple(issue.code for issue in semantic.issues)
        warnings = tuple(dict.fromkeys((*technical.warnings, *semantic.warnings)))

        if semantic.outcome == ReviewOutcome.PASS:
            return QACheckResult(
                passed=True,
                score=semantic.score,
                warnings=warnings,
                feedback=semantic.summary,
                outcome=semantic.outcome,
                retryable=False,
                repair_actions=repair_actions,
                evidence_refs=evidence_refs,
                reviewer_version=semantic.reviewer_version,
                criteria=semantic.criteria,
                semantic_issues=semantic.issues,
                evidence=semantic.evidence,
            )

        requires_human = semantic.outcome in {ReviewOutcome.REJECT, ReviewOutcome.UNKNOWN}
        if semantic.outcome == ReviewOutcome.UNKNOWN:
            issue_codes = (*issue_codes, "semantic_review_unknown")
            repair_actions = (*repair_actions, RepairAction.MANUAL_REVIEW)

        return QACheckResult(
            passed=False,
            score=semantic.score if semantic.score is not None else Decimal("0"),
            issues=tuple(dict.fromkeys(issue_codes)),
            warnings=warnings,
            feedback=semantic.summary,
            policy_violations=semantic.policy_violations,
            outcome=semantic.outcome,
            retryable=semantic.outcome == ReviewOutcome.REVISE,
            requires_human_review=requires_human,
            repair_actions=tuple(dict.fromkeys(repair_actions)),
            evidence_refs=evidence_refs,
            reviewer_version=semantic.reviewer_version,
            criteria=semantic.criteria,
            semantic_issues=semantic.issues,
            evidence=semantic.evidence,
        )


class ShadowSemanticCreativeQAChecker:
    """Record model review metadata without allowing it to gate workflow state."""

    def __init__(
        self,
        technical_checker: IQAChecker,
        semantic_reviewer: ISemanticReviewer,
    ) -> None:
        self._technical_checker = technical_checker
        self._semantic_reviewer = semantic_reviewer

    async def check(self, session: QASession) -> QACheckResult:
        technical = await self._technical_checker.check(session)
        if not technical.passed:
            return technical

        try:
            semantic = await self._semantic_reviewer.review(session)
        except SemanticReviewError:
            return replace(
                technical,
                warnings=tuple(dict.fromkeys((*technical.warnings, "semantic_shadow_unavailable"))),
            )
        evidence_refs = tuple(item.evidence_id for item in semantic.evidence)
        repair_actions = tuple(dict.fromkeys(issue.repair_action for issue in semantic.issues))
        warnings = tuple(
            dict.fromkeys(
                (
                    *technical.warnings,
                    *semantic.warnings,
                    "semantic_shadow_only",
                    f"semantic_shadow_outcome:{semantic.outcome.value}",
                )
            )
        )
        return QACheckResult(
            passed=True,
            score=technical.score,
            warnings=warnings,
            feedback=semantic.summary,
            retryable=False,
            repair_actions=repair_actions,
            evidence_refs=evidence_refs,
            reviewer_version=semantic.reviewer_version,
            criteria=semantic.criteria,
            semantic_issues=semantic.issues,
            evidence=semantic.evidence,
        )


__all__ = ["CompositeCreativeQAChecker", "ShadowSemanticCreativeQAChecker"]
