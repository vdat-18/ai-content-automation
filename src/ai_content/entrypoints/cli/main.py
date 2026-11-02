"""Local CLI for the Static Creative pilot harness.

Commands cover fake workflows and opt-in M1 preparation.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from ai_content.domains.marketing.creative.bootstrap import (
    CreativeRuntime,
    FixtureError,
    LocalPreparationCase,
    build_runtime,
    load_preparation_case,
    load_preparation_case_dir,
    load_work_item,
)
from ai_content.domains.marketing.creative.config.preparation import PreparationConfig
from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJob,
    CreativeJobId,
)
from ai_content.domains.marketing.creative.ports.preparation import PreparationError
from ai_content.domains.marketing.creative.ports.videos import (
    VideoGenerationError,
)
from ai_content.domains.marketing.creative.preparation_runtime import build_preparation_runtime
from ai_content.domains.marketing.creative_intake.bootstrap import (
    build_fixture_runtime as build_creative_intake_runtime,
)
from ai_content.domains.marketing.creative_intake.config.fixtures import (
    load_creative_intake_fixture,
)
from ai_content.domains.marketing.creative_intake.ports.interfaces import (
    CreativeIntakeInputDriftError,
)
from ai_content.settings import ApplicationSettings

DEFAULT_DB = Path(".creative-pilot") / "state.db"
DEFAULT_ARTIFACTS = Path(".creative-pilot") / "artifacts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicontent-ai",
        description="Static Creative pilot harness",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite state file")
    parser.add_argument(
        "--artifacts", type=Path, default=DEFAULT_ARTIFACTS, help="Artifact root dir"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser(
        "prepare-brief", help="Prepare one static brief without generating images"
    )
    prepare.add_argument(
        "--case-dir",
        type=Path,
        help="Directory containing work-item.json and context.json",
    )
    prepare.add_argument("--fixture", type=Path)
    prepare.add_argument("--context", type=Path)

    run_p = sub.add_parser("run", help="Run a work item fixture end-to-end")
    run_p.add_argument("--fixture", type=Path, required=True)

    replay_p = sub.add_parser(
        "replay", help="Re-run a fixture; duplicate source_run_id returns existing job"
    )
    replay_p.add_argument("--fixture", type=Path, required=True)

    inspect_p = sub.add_parser("inspect", help="Inspect a job by ID or source run")
    inspect_group = inspect_p.add_mutually_exclusive_group(required=True)
    inspect_group.add_argument("--job", help="Job ID")
    inspect_group.add_argument("--run", help="source_run_id")

    approve_p = sub.add_parser("approve", help="Approve the card of a job")
    approve_p.add_argument("--job", required=True)
    approve_p.add_argument("--reviewer", required=True)
    approve_p.add_argument("--reason", default=None)

    reject_p = sub.add_parser("reject", help="Reject the card of a job")
    reject_p.add_argument("--job", required=True)
    reject_p.add_argument("--reviewer", required=True)
    reject_p.add_argument("--reason", required=True)

    creative_intake = sub.add_parser(
        "run-creative-intake",
        help="Resolve synthetic H2/X1 demand and optionally run the fake Creative pipeline",
    )
    creative_intake.add_argument("--fixture", type=Path, required=True)
    creative_intake.add_argument("--dispatch-m1", action="store_true")
    creative_intake.add_argument(
        "--dispatch-creative",
        action="store_true",
        help="Run M1 and fake M2 through QA/revision to final human approval wait",
    )

    return parser


def print_job(job: CreativeJob, manifest_hint: str | None) -> None:
    _write_line(f"Job:          {job.job_id.value}")
    _write_line(f"Source run:   {job.source_run_id}")
    _write_line(f"Status:       {job.status.value}")
    _write_line(f"Context:      {job.context_ref}")
    if job.brief_ref:
        _write_line(f"Brief:        {job.brief_ref}")
    _write_line(f"Selected idea:{' ' + job.idea_id if job.idea_id else ' n/a'}")
    _write_line("Versions:")
    if not job.versions:
        _write_line("  (none)")
    for version in job.versions:
        outcome = (
            "PASS"
            if version.qa_passed is True
            else "FAIL"
            if version.qa_passed is False
            else "PENDING"
        )
        _write_line(
            f"  {version.version_id.value}  {outcome}"
            f"  score={version.qa_score}  cost={version.cost}"
        )
        if version.qa_issues:
            _write_line(f"    issues: {'; '.join(version.qa_issues)}")
        if version.qa_warnings:
            _write_line(f"    warnings: {'; '.join(version.qa_warnings)}")
    _write_line(f"Total cost:   {job.total_cost}")
    if job.card is not None:
        decision = job.card.decision.value if job.card.decision else "PENDING"
        _write_line(f"Approval:     {decision} on {job.card.final_version_ref}")
        if job.card.reviewer_id:
            _write_line(f"Reviewer:     {job.card.reviewer_id}")
        if job.card.reason:
            _write_line(f"Reason:       {job.card.reason}")
    _write_line(f"Lineage:      {len(job.lineage)} entries")
    if manifest_hint:
        _write_line(f"Manifest:     {manifest_hint}")


def _write_line(message: str) -> None:
    """Write user-facing CLI output; diagnostics continue to use Loguru."""
    sys.stdout.write(message + "\n")


def _load_cli_preparation_case(
    args: argparse.Namespace, *, max_context_bytes: int | None
) -> LocalPreparationCase:
    if args.case_dir is not None:
        if args.fixture is not None or args.context is not None:
            raise FixtureError("Use --case-dir or --fixture/--context, not both")
        return load_preparation_case_dir(
            args.case_dir,
            max_context_bytes=max_context_bytes,
        )
    if args.fixture is None or args.context is None:
        raise FixtureError("prepare-brief requires --case-dir or both --fixture and --context")
    return load_preparation_case(
        args.fixture,
        args.context,
        max_context_bytes=max_context_bytes,
    )


async def _load_job(runtime: CreativeRuntime, job: str | None, run: str | None):
    if job is not None:
        return await runtime.repository.get_job(CreativeJobId.from_string(job))
    return await runtime.repository.get_job_by_source_run_id(run or "")


async def _cmd_run(runtime: CreativeRuntime, args: argparse.Namespace) -> int:
    work_item = load_work_item(args.fixture)
    outcome = await runtime.run(work_item)
    job = outcome.result.job
    if job is None:
        logger.error("Run produced no job: {}", outcome.result.error)
        return 1
    if outcome.result.duplicate:
        _write_line(f"Duplicate trigger for {work_item.source_run_id}; existing job:")
        print_job(job, str(runtime.run_dir(work_item.source_run_id) / "manifest.json"))
        if not outcome.result.success:
            logger.error("Existing job cannot be resumed: {}", outcome.result.error)
            return 1
        return 0
    print_job(job, str(outcome.manifest_path) if outcome.manifest_path else None)
    if not outcome.result.success:
        logger.error(
            "Run ended in exception: {} ({})",
            outcome.result.exception_type,
            outcome.result.error,
        )
        return 1
    return 0


async def _cmd_inspect(runtime: CreativeRuntime, args: argparse.Namespace) -> int:
    job = await _load_job(runtime, args.job, args.run)
    if job is None:
        logger.error("Job not found (job={!r}, run={!r})", args.job, args.run)
        return 1
    manifest = None
    if job.source_run_id:
        manifest_path = runtime.run_dir(job.source_run_id) / "manifest.json"
        manifest = str(manifest_path) if manifest_path.exists() else None
    print_job(job, manifest)
    return 0


async def _cmd_decide(
    runtime: CreativeRuntime,
    args: argparse.Namespace,
    decision: ApprovalDecision,
) -> int:
    outcome = await runtime.decide(args.job, decision, args.reviewer, args.reason)
    job = outcome.result.job
    if job is None or not outcome.result.success:
        logger.error("Decision failed: {}", outcome.result.error)
        return 1
    print_job(job, str(outcome.manifest_path) if outcome.manifest_path else None)
    return 0


async def _async_main(args: argparse.Namespace, settings: ApplicationSettings) -> int:
    if args.command == "run-creative-intake":
        fixture = load_creative_intake_fixture(args.fixture)
        runtime = build_creative_intake_runtime(args.db, args.artifacts)
        try:
            outcome = await runtime.run(
                fixture,
                dispatch_m1=args.dispatch_m1,
                dispatch_creative=args.dispatch_creative,
                preparation_config=PreparationConfig.from_settings(settings),
            )
            for run in outcome.runs:
                handoff = run.release.handoff_state.value if run.release else "not_applicable"
                _write_line(
                    f"{run.trigger.source.value:20} {run.context.sku_id:20} "
                    f"{run.state.value:18} {handoff}"
                )
            _write_line(f"Runs:          {len(outcome.runs)}")
            _write_line(f"Duplicates:    {outcome.duplicate_count}")
            _write_line("External write: disabled")
            return 0
        finally:
            runtime.repository.close()
    if args.command == "prepare-brief":
        config = PreparationConfig.from_settings(settings)
        case = _load_cli_preparation_case(
            args,
            max_context_bytes=config.max_context_bytes,
        )
        runtime = build_preparation_runtime(
            args.db,
            args.artifacts,
            config,
            case.context,
            api_key=config.api_key,
        )
        try:
            result = await runtime.prepare(case.work_item)
            print_job(result.job, None)
            if result.duplicate:
                _write_line("Duplicate trigger; no new model calls")
            if result.output is not None:
                _write_line(
                    f"Summary: {runtime.store.artifacts.path(result.job.brief_ref).parent / 'summary.md'}"
                )
                _write_line("Brief only; no image generated, QA or business approval")
            if not result.success:
                logger.error("Preparation failed: {} ({})", result.exception_type, result.error)
            return 0 if result.success else 1
        finally:
            runtime.repository.close()
    runtime = build_runtime(args.db, args.artifacts)
    if args.command == "run":
        return await _cmd_run(runtime, args)
    if args.command == "replay":
        return await _cmd_run(runtime, args)
    if args.command == "inspect":
        return await _cmd_inspect(runtime, args)
    if args.command == "approve":
        return await _cmd_decide(runtime, args, ApprovalDecision.APPROVE)
    if args.command == "reject":
        return await _cmd_decide(runtime, args, ApprovalDecision.REJECT)
    logger.error("Unknown command: {}", args.command)
    return 2


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint; returns process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_async_main(args, ApplicationSettings()))
    except FixtureError as e:
        logger.error("Fixture error: {}", e)
        return 1
    except PreparationError as e:
        logger.error("Preparation/configuration error: {}", e)
        return 1
    except ValidationError:
        logger.error("Invalid configuration/input/review; check schema and required fields")
        return 1
    except VideoGenerationError as e:
        logger.error("Video pilot error: {}", e)
        return 1
    except CreativeIntakeInputDriftError as e:
        logger.error("Creative intake input drift: {}", e)
        return 1
    except OSError as e:
        logger.error("Pilot storage error: {}", e)
        return 1
    except ValueError as e:
        logger.error("Pilot input error: {}", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
