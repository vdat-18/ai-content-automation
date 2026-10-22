"""Generate, approve and execute bounded Creator outreach."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from ..domain.models import (
    CreatorContactTrigger,
    CreatorOutreachRun,
    DealApprovalCard,
    DealDecision,
    LarkHandoffPreview,
    OutreachApprovalCard,
    OutreachDecision,
    OutreachIssue,
    OutreachPlan,
    OutreachPlanVersion,
    OutreachPolicy,
    OutreachState,
    ReplyOutcome,
    ReplyRecord,
    ReviewOutcome,
)
from ..ports.interfaces import (
    CreatorOutreachInputDriftError,
    CreatorReplyInputDriftError,
    ICreatorOutreachRepository,
    IOutboundChannel,
    IOutreachPlanGenerator,
    IOutreachReviewer,
    IReplyEvidenceAppender,
)


@dataclass(frozen=True)
class CreatorOutreachRequest:
    trigger: CreatorContactTrigger
    policy: OutreachPolicy
    source_checksum_sha256: str
    prompt_version: str
    workflow_version: str
    max_revisions: int
    mapping_version: str
    target_base_ref: str
    field_mapping: tuple[tuple[str, str], ...]
    existing_record: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if len(self.source_checksum_sha256) != 64:
            raise ValueError("source_checksum_sha256 must be SHA-256")
        if self.max_revisions < 0:
            raise ValueError("max_revisions cannot be negative")
        if not self.prompt_version.strip() or not self.workflow_version.strip():
            raise ValueError("Prompt and workflow versions are required")


@dataclass(frozen=True)
class CreatorOutreachResult:
    run: CreatorOutreachRun
    duplicate: bool = False


def _policy_issues(
    plan: OutreachPlan,
    trigger: CreatorContactTrigger,
    policy: OutreachPolicy,
) -> tuple[OutreachIssue, ...]:
    issues: list[OutreachIssue] = []
    if plan.channel != policy.channel:
        issues.append(OutreachIssue("channel-mismatch", "Plan changed the approved channel."))
    if len(plan.followup_messages) != policy.max_followups:
        issues.append(
            OutreachIssue(
                "followup-count-mismatch",
                "The approved plan must contain exactly the bounded follow-up sequence.",
            )
        )
    unsupported_requests = set(plan.requested_fields) - set(policy.allowed_request_fields)
    if unsupported_requests:
        issues.append(
            OutreachIssue(
                "unsupported-request-field",
                "Plan requests fields outside policy: " + ", ".join(sorted(unsupported_requests)),
            )
        )
    if not set(plan.requested_fields).issubset(trigger.missing_fields):
        issues.append(
            OutreachIssue(
                "request-not-grounded",
                "Plan requests information not marked missing in the source evaluation.",
                trigger.evidence_refs,
            )
        )
    unsupported_evidence = set(plan.personalization_evidence_refs) - set(trigger.evidence_refs)
    if unsupported_evidence:
        issues.append(
            OutreachIssue(
                "personalization-evidence-mismatch",
                "Plan personalizes from evidence outside the pinned evaluation.",
                tuple(sorted(unsupported_evidence)),
            )
        )
    folded = plan.searchable_text.casefold()
    for term in policy.forbidden_terms:
        if term.casefold() in folded:
            issues.append(
                OutreachIssue(
                    "forbidden-commitment",
                    f"Outreach contains a prohibited commitment term: {term!r}.",
                    trigger.evidence_refs,
                )
            )
    return tuple(issues)


def _context_issues(request: CreatorOutreachRequest) -> tuple[OutreachIssue, ...]:
    issues: list[OutreachIssue] = []
    unsupported_missing = set(request.trigger.missing_fields) - set(
        request.policy.allowed_request_fields
    )
    if unsupported_missing:
        issues.append(
            OutreachIssue(
                "missing-field-not-requestable",
                "The source evaluation is missing fields not covered by the approved outreach "
                "policy: " + ", ".join(sorted(unsupported_missing)),
                request.trigger.evidence_refs,
            )
        )
    if (
        not request.mapping_version.strip()
        or not request.target_base_ref.strip()
        or not request.field_mapping
    ):
        issues.append(
            OutreachIssue(
                "reply-handoff-context-missing",
                "Reply evidence cannot be versioned without a Lark mapping preview context.",
            )
        )
    return tuple(issues)


class RunCreatorOutreach:
    def __init__(
        self,
        repository: ICreatorOutreachRepository,
        generator: IOutreachPlanGenerator,
        reviewer: IOutreachReviewer,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._reviewer = reviewer

    async def execute(self, request: CreatorOutreachRequest) -> CreatorOutreachResult:
        existing = await self._repository.get_by_source_run_id(request.trigger.source_run_id)
        if existing is not None:
            if existing.source_checksum_sha256 != request.source_checksum_sha256:
                raise CreatorOutreachInputDriftError(
                    f"source_run_id {request.trigger.source_run_id!r} was reused with changed input"
                )
            return CreatorOutreachResult(existing, True)

        now = datetime.now(UTC)
        run_id = "co-" + hashlib.sha256(request.trigger.source_run_id.encode()).hexdigest()[:20]
        context_issues = _context_issues(request)
        run = CreatorOutreachRun(
            run_id=run_id,
            source_run_id=request.trigger.source_run_id,
            source_checksum_sha256=request.source_checksum_sha256,
            trigger=request.trigger,
            policy=request.policy,
            state=(OutreachState.NEEDS_CONTEXT if context_issues else OutreachState.GENERATING),
            versions=(),
            issues=context_issues,
            outreach_approval=None,
            receipts=(),
            next_followup_at=None,
            reply=None,
            evaluation_update=None,
            deal_approval=None,
            handoff_preview=None,
            mapping_version=request.mapping_version,
            target_base_ref=request.target_base_ref,
            field_mapping=request.field_mapping,
            existing_record=request.existing_record,
            created_at=now,
            audit_log=(
                "source_evaluation:pinned",
                "context_resolution:blocked" if context_issues else "context_resolution:released",
            ),
        )
        if context_issues:
            await self._repository.save(run)
            return CreatorOutreachResult(run)
        revision_instructions: tuple[str, ...] = ()
        for version_number in range(1, request.max_revisions + 2):
            plan = await self._generator.generate(
                request.trigger, request.policy, revision_instructions
            )
            version_id = f"{run_id}-v{version_number}"
            version = OutreachPlanVersion(
                version_id=version_id,
                version_number=version_number,
                plan=plan,
                generator_version=self._generator.version,
                input_hash=request.source_checksum_sha256,
                prompt_version=request.prompt_version,
                policy_version=request.policy.version,
                workflow_version=request.workflow_version,
                created_at=datetime.now(UTC),
            )
            issues = _policy_issues(plan, request.trigger, request.policy)
            if issues:
                version = replace(
                    version, deterministic_issues=tuple(issue.code for issue in issues)
                )
                run = replace(
                    run,
                    state=OutreachState.EXCEPTION_POLICY,
                    versions=(*run.versions, version),
                    issues=issues,
                    audit_log=(*run.audit_log, f"policy_block:{version_id}"),
                )
                await self._repository.save(run)
                return CreatorOutreachResult(run)
            review = await self._reviewer.review(plan, request.trigger, version_number)
            version = replace(version, semantic_review=review)
            run = replace(
                run,
                state=OutreachState.CONTENT_QA,
                versions=(*run.versions, version),
                audit_log=(*run.audit_log, f"content_review:{version_id}:{review.outcome.value}"),
            )
            if review.outcome == ReviewOutcome.POLICY_BLOCK:
                run = replace(
                    run,
                    state=OutreachState.EXCEPTION_POLICY,
                    issues=tuple(
                        OutreachIssue("semantic-policy-block", issue, review.evidence_refs)
                        for issue in review.issues
                    ),
                )
                await self._repository.save(run)
                return CreatorOutreachResult(run)
            if review.outcome == ReviewOutcome.PASS:
                break
            revision_instructions = review.repair_instructions
            if version_number > request.max_revisions:
                run = replace(
                    run,
                    state=OutreachState.EXCEPTION_OPERATIONAL,
                    issues=(
                        OutreachIssue(
                            "revision-budget-exhausted",
                            "Outreach did not pass semantic review within the revision budget.",
                            review.evidence_refs,
                        ),
                    ),
                    audit_log=(*run.audit_log, "revision_budget:exhausted"),
                )
                await self._repository.save(run)
                return CreatorOutreachResult(run)
            run = replace(
                run,
                state=OutreachState.REVISION_PENDING,
                audit_log=(*run.audit_log, f"revision_requested:{version_id}"),
            )

        final = run.latest_version
        assert final is not None
        card = OutreachApprovalCard(
            plan_version_id=final.version_id,
            evaluation_id=request.trigger.evaluation_id,
            summary=(
                f"{request.trigger.brand_id} | {request.trigger.creator_alias} | {final.version_id}"
            ),
            evidence_refs=request.trigger.evidence_refs,
        )
        run = replace(
            run,
            state=OutreachState.AWAITING_APPROVAL,
            outreach_approval=card,
            audit_log=(*run.audit_log, f"approval_ready:{final.version_id}"),
        )
        await self._repository.save(run)
        return CreatorOutreachResult(run)


class DecideCreatorOutreach:
    def __init__(self, repository: ICreatorOutreachRepository, channel: IOutboundChannel) -> None:
        self._repository = repository
        self._channel = channel

    async def execute(
        self,
        run_id: str,
        plan_version_id: str,
        evaluation_id: str,
        decision: OutreachDecision,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> CreatorOutreachRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise ValueError("Creator outreach run not found")
        updated = run.decide_outreach(
            decision,
            plan_version_id,
            evaluation_id,
            reviewer_alias,
            reason,
            decided_at,
        )
        if decision == OutreachDecision.APPROVE:
            version = updated.latest_version
            assert version is not None
            receipt = await self._channel.send(
                run_id,
                version,
                version.plan.initial_message,
                0,
                f"{run_id}:{version.version_id}:initial",
                decided_at,
            )
            updated = replace(
                updated,
                state=OutreachState.WAITING_REPLY,
                receipts=(*updated.receipts, receipt),
                next_followup_at=decided_at
                + timedelta(hours=updated.policy.followup_interval_hours),
                audit_log=(*updated.audit_log, f"delivery_acknowledged:{receipt.receipt_id}"),
            )
        await self._repository.save(updated)
        return updated


class ProcessDueCreatorFollowups:
    def __init__(self, repository: ICreatorOutreachRepository, channel: IOutboundChannel) -> None:
        self._repository = repository
        self._channel = channel

    async def execute(
        self, as_of: datetime, run_id: str | None = None
    ) -> tuple[CreatorOutreachRun, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Follow-up processing time must include timezone information")
        candidates = (
            ([run] if run_id and (run := await self._repository.get(run_id)) is not None else [])
            if run_id
            else await self._repository.list()
        )
        updated_runs: list[CreatorOutreachRun] = []
        for run in candidates:
            if (
                run.state != OutreachState.WAITING_REPLY
                or run.reply is not None
                or run.next_followup_at is None
                or run.next_followup_at > as_of
            ):
                continue
            version = run.latest_version
            assert version is not None
            sent_followups = sum(receipt.sequence > 0 for receipt in run.receipts)
            if sent_followups >= run.policy.max_followups:
                updated = replace(
                    run,
                    state=OutreachState.CLOSED_NO_REPLY,
                    next_followup_at=None,
                    audit_log=(*run.audit_log, "outreach_closed:no_reply"),
                )
            else:
                sequence = sent_followups + 1
                receipt = await self._channel.send(
                    run.run_id,
                    version,
                    version.plan.followup_messages[sent_followups],
                    sequence,
                    f"{run.run_id}:{version.version_id}:followup:{sequence}",
                    as_of,
                )
                updated = replace(
                    run,
                    receipts=(*run.receipts, receipt),
                    next_followup_at=as_of + timedelta(hours=run.policy.followup_interval_hours),
                    audit_log=(*run.audit_log, f"delivery_acknowledged:{receipt.receipt_id}"),
                )
            await self._repository.save(updated)
            updated_runs.append(updated)
        return tuple(updated_runs)


class RecordCreatorReply:
    def __init__(
        self,
        repository: ICreatorOutreachRepository,
        evidence_appender: IReplyEvidenceAppender,
    ) -> None:
        self._repository = repository
        self._evidence_appender = evidence_appender

    async def execute(self, run_id: str, reply: ReplyRecord) -> CreatorOutreachResult:
        run = await self._repository.get(run_id)
        if run is None:
            raise ValueError("Creator outreach run not found")
        if run.reply is not None:
            if run.reply.event_id == reply.event_id:
                if run.reply.event_checksum_sha256 != reply.event_checksum_sha256:
                    raise CreatorReplyInputDriftError(
                        f"reply event {reply.event_id!r} was reused with changed input"
                    )
                return CreatorOutreachResult(run, True)
            raise ValueError("This pilot records one terminal reply event per outreach run")
        if run.state not in {OutreachState.WAITING_REPLY, OutreachState.CLOSED_NO_REPLY}:
            raise ValueError("Creator reply can only attach to an active or timed-out outreach")
        late = run.state == OutreachState.CLOSED_NO_REPLY
        if reply.outcome == ReplyOutcome.DECLINED:
            updated = replace(
                run,
                state=OutreachState.CLOSED_DECLINED,
                reply=reply,
                next_followup_at=None,
                audit_log=(*run.audit_log, f"reply:declined:{reply.event_id}"),
            )
        else:
            evaluation = await self._evidence_appender.append(run, reply)
            ready = (
                reply.outcome == ReplyOutcome.INTERESTED
                and evaluation.evaluation_state == "ready_for_review"
                and evaluation.lark_preview_state == "preview_ready"
            )
            deal_card = (
                DealApprovalCard(
                    reply_event_id=reply.event_id,
                    evaluation_id=evaluation.evaluation_id,
                    summary=(
                        f"{run.trigger.brand_id} | {run.trigger.creator_alias} | "
                        f"{evaluation.evaluation_id}"
                    ),
                    evidence_refs=(reply.source_ref, evaluation.preview_ref),
                )
                if ready
                else None
            )
            updated = replace(
                run,
                state=(
                    OutreachState.AWAITING_DEAL_APPROVAL
                    if ready
                    else OutreachState.NEEDS_BUSINESS_REVIEW
                ),
                reply=reply,
                evaluation_update=evaluation,
                deal_approval=deal_card,
                next_followup_at=None,
                audit_log=(
                    *run.audit_log,
                    f"reply:{reply.outcome.value}:{reply.event_id}",
                    *(("reply:late",) if late else ()),
                    f"evaluation_appended:{evaluation.evaluation_id}",
                ),
            )
        await self._repository.save(updated)
        return CreatorOutreachResult(updated)


class DecideCreatorDeal:
    def __init__(self, repository: ICreatorOutreachRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        run_id: str,
        reply_event_id: str,
        evaluation_id: str,
        decision: DealDecision,
        reviewer_alias: str,
        reason: str,
        decided_at: datetime,
    ) -> CreatorOutreachRun:
        if decided_at.tzinfo is None or decided_at.utcoffset() is None:
            raise ValueError("Deal decision time must include timezone information")
        run = await self._repository.get(run_id)
        if run is None:
            raise ValueError("Creator outreach run not found")
        card = run.deal_approval
        if run.state != OutreachState.AWAITING_DEAL_APPROVAL or card is None:
            raise ValueError("Creator deal is not awaiting approval")
        if reply_event_id != card.reply_event_id or evaluation_id != card.evaluation_id:
            raise ValueError("Deal decision must pin the current reply and evaluation")
        if not reviewer_alias.strip() or not reason.strip():
            raise ValueError("Reviewer alias and reason are required")
        decided = replace(
            card,
            decision=decision,
            reviewer_alias=reviewer_alias,
            reason=reason,
            decided_at=decided_at,
        )
        handoff = None
        state = OutreachState.NEEDS_BUSINESS_REVIEW
        if decision == DealDecision.APPROVE:
            assert run.evaluation_update is not None
            handoff = LarkHandoffPreview(
                preview_id=f"clp-{run.run_id}",
                candidate_id=run.trigger.candidate_id,
                evaluation_id=evaluation_id,
                lark_preview_ref=run.evaluation_update.preview_ref,
                prohibited_external_actions=(
                    "write_lark_base",
                    "create_booking_or_contract",
                    "commit_rate_or_usage_rights",
                    "send_payment_or_product",
                ),
            )
            state = OutreachState.READY_FOR_LARK_PREVIEW
        elif decision == DealDecision.REJECT:
            state = OutreachState.REJECTED
        updated = replace(
            run,
            state=state,
            deal_approval=decided,
            handoff_preview=handoff,
            audit_log=(*run.audit_log, f"deal_decision:{decision.value}:{evaluation_id}"),
        )
        await self._repository.save(updated)
        return updated


__all__ = [
    "CreatorOutreachRequest",
    "CreatorOutreachResult",
    "DecideCreatorDeal",
    "DecideCreatorOutreach",
    "ProcessDueCreatorFollowups",
    "RecordCreatorReply",
    "RunCreatorOutreach",
]
