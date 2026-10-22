"""Run one synthetic-first Email campaign production workflow."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from ..domain.models import (
    ContextComponent,
    ContextStatus,
    EmailApprovalCard,
    EmailContextSnapshot,
    EmailPackage,
    EmailPackageVersion,
    EmailProductionJob,
    EmailProductionState,
    EmailTrigger,
    PreflightReference,
    ProductionIssue,
    ReviewOutcome,
)
from ..ports.interfaces import (
    EmailProductionInputDriftError,
    IEmailPackageGenerator,
    IEmailPreflightGateway,
    IEmailProductionRepository,
    IEmailSemanticReviewer,
)

_REQUIRED_COMPONENTS = set(ContextComponent)


@dataclass(frozen=True)
class EmailProductionRequest:
    trigger: EmailTrigger
    context: EmailContextSnapshot
    source_checksum_sha256: str
    prompt_version: str
    policy_version: str
    workflow_version: str
    max_revisions: int

    def __post_init__(self) -> None:
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        if self.max_revisions < 0:
            raise ValueError("max_revisions cannot be negative")
        if not all(
            value.strip()
            for value in (self.prompt_version, self.policy_version, self.workflow_version)
        ):
            raise ValueError("Prompt, policy and workflow versions are required")


@dataclass(frozen=True)
class EmailProductionResult:
    job: EmailProductionJob
    duplicate: bool = False


def _context_issues(
    trigger: EmailTrigger,
    context: EmailContextSnapshot,
    now: datetime,
) -> tuple[ProductionIssue, ...]:
    issues: list[ProductionIssue] = []
    if trigger.brand_id != context.brand_id or trigger.account_id != context.account_id:
        issues.append(
            ProductionIssue(
                "trigger-context-identity-conflict",
                "Trigger and context must reference the same Brand and Klaviyo account.",
            )
        )
    if trigger.scheduled_at.tzinfo is None or not context.timezone.strip():
        issues.append(
            ProductionIssue("send-context-invalid", "A timezone-aware send proposal is required.")
        )
    components = {item.component: item for item in context.components}
    for component in sorted(_REQUIRED_COMPONENTS, key=lambda item: item.value):
        evidence = components.get(component)
        if evidence is None:
            issues.append(
                ProductionIssue(
                    f"{component.value}-missing",
                    f"Required context component {component.value} is absent.",
                )
            )
            continue
        if evidence.status == ContextStatus.UNKNOWN:
            issues.append(
                ProductionIssue(
                    f"{component.value}-unknown",
                    evidence.detail or f"Required context component {component.value} is unknown.",
                    evidence.evidence_refs,
                )
            )
        elif evidence.status == ContextStatus.CONFLICT:
            issues.append(
                ProductionIssue(
                    f"{component.value}-conflict",
                    evidence.detail
                    or f"Required context component {component.value} has conflicting values.",
                    evidence.evidence_refs,
                )
            )
        if evidence.valid_until is not None and evidence.valid_until <= now:
            issues.append(
                ProductionIssue(
                    f"{component.value}-expired",
                    f"Required context component {component.value} has expired.",
                    evidence.evidence_refs,
                )
            )
    return tuple(issues)


def _context_state(issues: tuple[ProductionIssue, ...]) -> EmailProductionState:
    if any("conflict" in issue.code for issue in issues):
        return EmailProductionState.BLOCKED_CONFLICT
    return EmailProductionState.NEEDS_CONTEXT


def _policy_issues(
    package: EmailPackage,
    context: EmailContextSnapshot,
) -> tuple[ProductionIssue, ...]:
    issues: list[ProductionIssue] = []
    folded = package.searchable_text.casefold()
    for phrase in context.forbidden_phrases:
        if phrase.casefold() in folded:
            issues.append(
                ProductionIssue(
                    "forbidden-phrase",
                    f"Generated Email contains a prohibited phrase: {phrase!r}.",
                    context.evidence_refs,
                )
            )
    for punctuation in context.forbidden_punctuation:
        if punctuation in package.searchable_text:
            issues.append(
                ProductionIssue(
                    "forbidden-punctuation",
                    f"Generated Email contains prohibited punctuation: {punctuation!r}.",
                    context.evidence_refs,
                )
            )
    for brand_term in context.cross_brand_terms:
        if brand_term.casefold() in folded:
            issues.append(
                ProductionIssue(
                    "cross-brand-mention",
                    f"Generated Email mentions another brand: {brand_term!r}.",
                    context.evidence_refs,
                )
            )
    if package.offer_ref != context.offer_ref:
        issues.append(
            ProductionIssue(
                "offer-reference-mismatch",
                "Generated Email does not pin the approved offer state from context.",
                context.evidence_refs,
            )
        )
    if (
        package.audience_ref != context.audience_ref
        or package.exclusion_ref != context.exclusion_ref
    ):
        issues.append(
            ProductionIssue(
                "audience-policy-mismatch",
                "Generated Email changed the approved audience or exclusion reference.",
                context.evidence_refs,
            )
        )
    if package.timezone != context.timezone:
        issues.append(
            ProductionIssue(
                "timezone-mismatch",
                "Generated Email timezone differs from the pinned account timezone.",
                context.evidence_refs,
            )
        )
    unsupported_claims = set(package.claim_refs) - set(context.approved_claim_refs)
    if unsupported_claims:
        issues.append(
            ProductionIssue(
                "unsupported-claim-reference",
                "Generated Email uses claim references not approved in this context: "
                + ", ".join(sorted(unsupported_claims)),
                context.evidence_refs,
            )
        )
    product_refs = {ref for section in package.sections for ref in section.product_refs}
    if not product_refs.issubset(context.product_refs):
        issues.append(
            ProductionIssue(
                "product-reference-mismatch",
                "Generated Email references a product outside the pinned collection context.",
                context.evidence_refs,
            )
        )
    asset_refs = {ref for section in package.sections for ref in section.asset_refs}
    if not asset_refs.issubset(context.asset_refs):
        issues.append(
            ProductionIssue(
                "asset-reference-mismatch",
                "Generated Email references an asset outside the approved Brand/Product context.",
                context.evidence_refs,
            )
        )
    return tuple(issues)


class RunEmailProduction:
    """Generate, review, preflight and prepare one Email approval card."""

    def __init__(
        self,
        repository: IEmailProductionRepository,
        generator: IEmailPackageGenerator,
        reviewer: IEmailSemanticReviewer,
        preflight: IEmailPreflightGateway,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._reviewer = reviewer
        self._preflight = preflight

    async def execute(self, request: EmailProductionRequest) -> EmailProductionResult:
        existing = await self._repository.get_by_source_run_id(request.trigger.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise EmailProductionInputDriftError(
                    f"source_run_id {request.trigger.source_run_id!r} was reused with changed input"
                )
            return EmailProductionResult(existing, True)

        now = datetime.now(UTC)
        job_id = "ep-" + hashlib.sha256(request.trigger.source_run_id.encode()).hexdigest()[:20]
        context_issues = _context_issues(request.trigger, request.context, now)
        if context_issues:
            job = EmailProductionJob(
                job_id=job_id,
                source_run_id=request.trigger.source_run_id,
                source_checksum_sha256=request.source_checksum_sha256,
                trigger=request.trigger,
                context=request.context,
                state=_context_state(context_issues),
                versions=(),
                issues=context_issues,
                preflight=None,
                approval_card=None,
                handoff_preview=None,
                created_at=now,
                audit_log=("context_resolution:blocked",),
            )
            await self._repository.save(job)
            return EmailProductionResult(job)

        job = EmailProductionJob(
            job_id=job_id,
            source_run_id=request.trigger.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            trigger=request.trigger,
            context=request.context,
            state=EmailProductionState.GENERATING,
            versions=(),
            issues=(),
            preflight=None,
            approval_card=None,
            handoff_preview=None,
            created_at=now,
            audit_log=("context_resolution:released",),
        )
        revision_instructions: tuple[str, ...] = ()
        for version_number in range(1, request.max_revisions + 2):
            package = await self._generator.generate(
                request.trigger, request.context, revision_instructions
            )
            version_id = f"{job_id}-v{version_number}"
            version = EmailPackageVersion(
                version_id=version_id,
                version_number=version_number,
                package=package,
                generator_version=self._generator.version,
                input_hash=request.source_checksum_sha256,
                prompt_version=request.prompt_version,
                policy_version=request.policy_version,
                workflow_version=request.workflow_version,
                created_at=datetime.now(UTC),
                preview_ref=(
                    f"email-production/{request.trigger.source_run_id}/versions/"
                    f"v{version_number}/preview.html"
                ),
            )
            policy_issues = _policy_issues(package, request.context)
            if policy_issues:
                version = replace(
                    version,
                    deterministic_issues=tuple(issue.code for issue in policy_issues),
                )
                job = replace(
                    job,
                    state=EmailProductionState.EXCEPTION_POLICY,
                    versions=(*job.versions, version),
                    issues=policy_issues,
                    audit_log=(*job.audit_log, f"policy_block:{version_id}"),
                )
                await self._repository.save(job)
                return EmailProductionResult(job)

            review = await self._reviewer.review(package, request.context, version_number)
            version = replace(version, semantic_review=review)
            job = replace(
                job,
                state=EmailProductionState.CONTENT_QA,
                versions=(*job.versions, version),
                audit_log=(*job.audit_log, f"content_review:{version_id}:{review.outcome.value}"),
            )
            if review.outcome == ReviewOutcome.POLICY_BLOCK:
                job = replace(
                    job,
                    state=EmailProductionState.EXCEPTION_POLICY,
                    issues=tuple(
                        ProductionIssue("semantic-policy-block", issue, review.evidence_refs)
                        for issue in review.issues
                    ),
                )
                await self._repository.save(job)
                return EmailProductionResult(job)
            if review.outcome == ReviewOutcome.PASS:
                break
            revision_instructions = review.repair_instructions
            if version_number > request.max_revisions:
                job = replace(
                    job,
                    state=EmailProductionState.EXCEPTION_OPERATIONAL,
                    issues=tuple(
                        ProductionIssue("revision-budget-exhausted", issue, review.evidence_refs)
                        for issue in review.issues
                    ),
                    audit_log=(*job.audit_log, "revision_budget:exhausted"),
                )
                await self._repository.save(job)
                return EmailProductionResult(job)
            job = replace(
                job,
                state=EmailProductionState.REVISION_PENDING,
                audit_log=(*job.audit_log, f"revision_requested:{version_id}"),
            )

        final_version = job.latest_version
        assert final_version is not None
        job = replace(job, state=EmailProductionState.PREFLIGHT_CHECKING)
        preflight = await self._preflight.evaluate(job, final_version)
        reference = PreflightReference(
            run_id=preflight.run_id,
            evaluation_id=preflight.evaluation_id,
            email_version_id=final_version.version_id,
            classification=preflight.classification,
            allowed_for_approval=preflight.allowed_for_approval,
            warnings=preflight.warnings,
        )
        if not preflight.allowed_for_approval:
            job = replace(
                job,
                state=EmailProductionState.PREFLIGHT_BLOCKED,
                preflight=reference,
                issues=(
                    ProductionIssue(
                        "preflight-not-ready",
                        "Exact-version N3 pre-send evidence is blocking, unknown or conflicting.",
                        (preflight.run_id, preflight.evaluation_id),
                    ),
                ),
                audit_log=(*job.audit_log, f"preflight:blocked:{preflight.evaluation_id}"),
            )
        else:
            card = EmailApprovalCard(
                email_version_id=final_version.version_id,
                preflight_evaluation_id=preflight.evaluation_id,
                summary=(
                    f"{request.context.brand_id} | {final_version.package.campaign_name} | "
                    f"{final_version.version_id}"
                ),
                evidence_refs=tuple(
                    dict.fromkeys(
                        (*request.context.evidence_refs, preflight.run_id, preflight.evaluation_id)
                    )
                ),
                warnings=preflight.warnings,
            )
            job = replace(
                job,
                state=EmailProductionState.AWAITING_APPROVAL,
                preflight=reference,
                approval_card=card,
                audit_log=(*job.audit_log, f"approval_ready:{final_version.version_id}"),
            )
        await self._repository.save(job)
        return EmailProductionResult(job)


__all__ = ["EmailProductionRequest", "EmailProductionResult", "RunEmailProduction"]
