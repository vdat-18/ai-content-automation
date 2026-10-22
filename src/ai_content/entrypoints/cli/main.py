"""Local CLI for the Static Creative pilot harness.

Commands cover fake workflows, opt-in M1 preparation and image evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from ai_content.domains.marketing.creative.adapters.postgres_repository import (
    PostgresCreativeRepository,
)
from ai_content.domains.marketing.creative.bootstrap import (
    CreativeRuntime,
    FixtureError,
    LocalPreparationCase,
    build_runtime,
    load_preparation_case,
    load_preparation_case_dir,
    load_work_item,
)
from ai_content.domains.marketing.creative.config.images import (
    HistoricalHumanReview,
    ImageBackendConfig,
    load_image_config,
    load_image_dataset,
)
from ai_content.domains.marketing.creative.config.loader import ConfigError
from ai_content.domains.marketing.creative.config.preparation import load_preparation_config
from ai_content.domains.marketing.creative.config.reviewers import (
    load_semantic_reviewer_config,
)
from ai_content.domains.marketing.creative.config.rubrics import load_review_rubric
from ai_content.domains.marketing.creative.config.segmentation import (
    load_product_segmenter_config,
)
from ai_content.domains.marketing.creative.config.videos import load_video_config
from ai_content.domains.marketing.creative.domain.entities import (
    ApprovalDecision,
    CreativeJob,
    CreativeJobId,
)
from ai_content.domains.marketing.creative.image_pilot import (
    HumanImageReview,
    assess_golden_dataset,
    benchmark_images,
    initialize_image_example,
    load_human_criterion_reviews,
    prepare_historical_review_pack,
    read_evaluation_results,
    record_historical_review,
    record_image_review,
    summarize_image_evaluation,
)
from ai_content.domains.marketing.creative.lineage_audit import (
    build_static_lineage_crosswalk,
    write_static_lineage_crosswalk,
)
from ai_content.domains.marketing.creative.marketing_video import (
    load_video_marketing_plan,
    review_video_marketing,
    run_video_marketing,
)
from ai_content.domains.marketing.creative.ports.contracts import StaticCreativeInput
from ai_content.domains.marketing.creative.ports.images import ImageGenerationError
from ai_content.domains.marketing.creative.ports.preparation import PreparationError
from ai_content.domains.marketing.creative.ports.videos import (
    VideoGenerationError,
    VideoGenerationRequest,
)
from ai_content.domains.marketing.creative.preparation_runtime import build_preparation_runtime
from ai_content.domains.marketing.creative.video_pilot import (
    build_video_backend,
    generate_video_clip,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import (
    build_fixture_runtime as build_creative_feedback_runtime,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import (
    build_read_runtime as build_creative_feedback_read_runtime,
)
from ai_content.domains.marketing.creative_feedback.config.fixtures import (
    load_creative_feedback_fixture,
)
from ai_content.domains.marketing.creative_feedback.config.learning import (
    load_performance_learning_config,
)
from ai_content.domains.marketing.creative_feedback.domain.models import FeedbackDecision
from ai_content.domains.marketing.creative_feedback.ports.interfaces import (
    CreativeFeedbackInputDriftError,
)
from ai_content.domains.marketing.creative_intake.application.projections import (
    project_feedback_trigger,
    project_performance_trigger,
)
from ai_content.domains.marketing.creative_intake.bootstrap import (
    build_fixture_runtime as build_creative_intake_runtime,
)
from ai_content.domains.marketing.creative_intake.config.fixtures import (
    CreativeIntakeFixture,
    case_for_trigger,
    load_creative_intake_fixture,
)
from ai_content.domains.marketing.creative_intake.ports.interfaces import (
    CreativeIntakeInputDriftError,
)
from ai_content.domains.marketing.creative_loop.bootstrap import (
    build_runtime as build_creative_loop_runtime,
)
from ai_content.domains.marketing.creative_loop.ports.interfaces import (
    CreativeLoopEventDriftError,
    CreativeLoopInputDriftError,
)
from ai_content.domains.marketing.performance_data.bootstrap import (
    build_fixture_runtime as build_gmc_runtime,
)
from ai_content.domains.marketing.performance_data.config.fixtures import load_gmc_fixture
from ai_content.domains.marketing.performance_data.ports.interfaces import InputDriftError
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    build_fixture_runtime as build_performance_decision_runtime,
)
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    build_read_runtime as build_performance_decision_read_runtime,
)
from ai_content.domains.marketing.performance_decisions.config.fixtures import (
    load_performance_decision_fixture,
)
from ai_content.domains.marketing.performance_decisions.config.opportunity import (
    load_opportunity_config,
)
from ai_content.domains.marketing.performance_decisions.domain.models import (
    PerformanceDecision,
)
from ai_content.domains.marketing.performance_decisions.ports.interfaces import (
    PerformanceInputDriftError,
)
from ai_content.platform.ai_usage import AIUsageTracker, PostgresAIUsageRepository
from ai_content.platform.artifacts import ArtifactKind, ArtifactService, PostgresArtifactCatalog
from ai_content.platform.database import Database
from ai_content.settings import ApplicationSettings

DEFAULT_DB = Path(".creative-pilot") / "state.db"
DEFAULT_ARTIFACTS = Path(".creative-pilot") / "artifacts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicontent-ai",
        description="Static Creative pilot harness and image evaluation",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite state file")
    parser.add_argument(
        "--artifacts", type=Path, default=DEFAULT_ARTIFACTS, help="Artifact root dir"
    )
    parser.add_argument("--config", type=Path, default=Path("config"), help="Config root dir")
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
    prepare.add_argument("--preparation-config", type=Path, required=True)

    run_p = sub.add_parser("run", help="Run a work item fixture end-to-end")
    run_p.add_argument("--fixture", type=Path, required=True)
    run_p.add_argument("--image-config", type=Path)
    run_p.add_argument("--image-dataset", type=Path)
    run_p.add_argument("--case")
    run_p.add_argument("--seed", type=int, default=0)

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

    init_p = sub.add_parser("init-image-eval", help="Create a synthetic image smoke dataset")
    init_p.add_argument("--output", type=Path, required=True)
    benchmark = sub.add_parser(
        "benchmark-images", help="Evaluate fixed image cases, one GPU job at a time"
    )
    benchmark.add_argument("--dataset", type=Path, required=True)
    benchmark.add_argument("--image-config", type=Path, action="append", required=True)
    benchmark.add_argument("--seed", type=int, action="append", required=True)
    benchmark.add_argument("--case")
    benchmark.add_argument("--output", type=Path, default=Path(".creative-pilot/evaluations"))
    video = sub.add_parser(
        "generate-video", help="Generate one short video clip through a configured provider"
    )
    video.add_argument(
        "--video-config",
        type=Path,
        help="Defaults to AIC_AI_VIDEO_CONFIG from the process environment",
    )
    video.add_argument("--prompt", required=True)
    video.add_argument("--seconds", type=int, default=8)
    video.add_argument("--size", default="1280x720")
    video.add_argument("--quality")
    video.add_argument("--output", type=Path, required=True)
    video_plan = sub.add_parser(
        "run-marketing-video", help="Run a bounded multi-shot Marketing video pilot"
    )
    video_plan.add_argument("--plan", type=Path, required=True)
    video_plan.add_argument("--video-config", type=Path)
    video_plan.add_argument("--output", type=Path, required=True)
    video_review = sub.add_parser(
        "review-marketing-video", help="Record a decision on the exact final Marketing video"
    )
    video_review.add_argument("--run-dir", type=Path, required=True)
    video_review.add_argument("--decision", choices=["accept", "revise", "reject"], required=True)
    video_review.add_argument("--reason", required=True)
    review = sub.add_parser("review-image", help="Record a human image evaluation")
    review.add_argument("--run-dir", type=Path, required=True)
    review.add_argument("--sample", required=True)
    review.add_argument(
        "--reviewer", required=True, help="Internal reviewer alias, not personal contact"
    )
    review.add_argument("--decision", choices=["accept", "revise", "reject"], required=True)
    review.add_argument("--reason", required=True)
    review.add_argument("--critical-product-error", action="store_true")
    review.add_argument("--rubric-version")
    review.add_argument("--rubric", type=Path)
    review.add_argument(
        "--criteria",
        type=Path,
        help="JSON list of versioned rubric criterion results",
    )
    report = sub.add_parser("report-images", help="Rebuild metrics from results and human reviews")
    report.add_argument("--run-dir", type=Path, required=True)
    report.add_argument("--rubric", type=Path)
    validate_dataset = sub.add_parser(
        "validate-golden-dataset",
        help="Check local assets, permissions and human labels before calibration",
    )
    validate_dataset.add_argument("--dataset", type=Path, required=True)
    validate_dataset.add_argument("--rubric", type=Path, required=True)
    audit_lineage = sub.add_parser(
        "audit-static-lineage",
        help="Cross-check historical Static task rows against local calibration images",
    )
    audit_lineage.add_argument("--manifest", type=Path, required=True)
    audit_lineage.add_argument("--dataset", type=Path, required=True)
    audit_lineage.add_argument("--rubric", type=Path, required=True)
    audit_lineage.add_argument("--output", type=Path, required=True)
    prepare_history = sub.add_parser(
        "prepare-golden-review",
        help="Create a blind review pack for historical golden candidates",
    )
    prepare_history.add_argument("--dataset", type=Path, required=True)
    prepare_history.add_argument("--rubric", type=Path, required=True)
    prepare_history.add_argument("--output", type=Path, required=True)
    record_history = sub.add_parser(
        "review-golden-image",
        help="Append one structured human review to a local golden dataset",
    )
    record_history.add_argument("--dataset", type=Path, required=True)
    record_history.add_argument("--review-pack", type=Path, required=True)
    record_history.add_argument("--sample", required=True)
    record_history.add_argument(
        "--reviewer", required=True, help="Internal reviewer alias, not personal contact"
    )
    record_history.add_argument("--decision", choices=["accept", "revise", "reject"], required=True)
    record_history.add_argument("--reason", required=True)
    record_history.add_argument("--critical-product-error", action="store_true")
    record_history.add_argument("--rubric", type=Path, required=True)
    record_history.add_argument("--criteria", type=Path, required=True)
    gmc = sub.add_parser(
        "run-gmc-ingestion", help="Run a synthetic, chunked and read-only GMC ingestion"
    )
    gmc.add_argument("--fixture", type=Path, required=True)
    performance_decision = sub.add_parser(
        "run-performance-decision",
        help="Run synthetic Performance rules and prepare Creative demand previews",
    )
    performance_decision.add_argument("--fixture", type=Path, required=True)
    performance_decision.add_argument(
        "--opportunity-config",
        type=Path,
        help="Run optional BAML Creative Opportunity analysis in shadow mode",
    )
    creative_feedback = sub.add_parser(
        "run-creative-feedback",
        help="Run synthetic exact-version Creative feedback lineage",
    )
    creative_feedback.add_argument("--fixture", type=Path, required=True)
    creative_feedback.add_argument(
        "--learning-config",
        type=Path,
        help="Run optional Performance Learning analysis in shadow mode",
    )
    creative_intake = sub.add_parser(
        "run-creative-intake",
        help="Resolve synthetic H2/X1 demand and optionally run the fake Creative pipeline",
    )
    creative_intake.add_argument("--fixture", type=Path, required=True)
    creative_intake.add_argument("--source", choices=["performance", "feedback"])
    creative_intake.add_argument("--source-run-id")
    creative_intake.add_argument("--context-snapshot-id")
    creative_intake.add_argument("--dispatch-m1", action="store_true")
    creative_intake.add_argument(
        "--dispatch-creative",
        action="store_true",
        help="Run M1 and fake M2 through QA/revision to final human approval wait",
    )
    creative_intake.add_argument(
        "--preparation-config",
        type=Path,
        default=Path("config/preparation/synthetic.json"),
    )
    run_loop = sub.add_parser(
        "run-creative-loop",
        help="Start the unified synthetic H2 -> Creative -> X1 closed loop",
    )
    run_loop.add_argument("--fixture", type=Path)
    run_loop.add_argument("--local-loop", type=Path)
    run_loop.add_argument("--preparation-config", type=Path)
    run_loop.add_argument("--image-config", type=Path)
    run_loop.add_argument("--review-config", type=Path)
    run_loop.add_argument("--learning-config", type=Path)
    decide_loop = sub.add_parser(
        "decide-creative-loop",
        help="Decide an exact demand, Creative or feedback lesson gate",
    )
    decide_loop.add_argument("--fixture", type=Path)
    decide_loop.add_argument("--local-loop", type=Path)
    decide_loop.add_argument("--preparation-config", type=Path)
    decide_loop.add_argument("--image-config", type=Path)
    decide_loop.add_argument("--review-config", type=Path)
    decide_loop.add_argument("--learning-config", type=Path)
    decide_loop.add_argument("--learning-proposal-id")
    decide_loop.add_argument("--run-id", required=True)
    decide_loop.add_argument("--gate", choices=["demand", "creative", "lesson"], required=True)
    decide_loop.add_argument("--pinned-id")
    decide_loop.add_argument("--decision", choices=["approve", "reject", "defer"], required=True)
    decide_loop.add_argument("--reviewer", required=True)
    decide_loop.add_argument("--reason", required=True)
    ads_loop = sub.add_parser(
        "record-creative-loop-ads-outcome",
        help="Inject the fixture's explicit synthetic Ads outcome",
    )
    ads_loop.add_argument("--fixture", type=Path)
    ads_loop.add_argument("--local-loop", type=Path)
    ads_loop.add_argument("--run-id", required=True)
    inspect_loop = sub.add_parser(
        "inspect-creative-loop", help="Inspect one unified Creative loop run"
    )
    inspect_loop.add_argument("--fixture", type=Path)
    inspect_loop.add_argument("--local-loop", type=Path)
    inspect_loop.add_argument("--run-id", required=True)

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


async def _cmd_run_postgres_image(
    args: argparse.Namespace,
    settings: ApplicationSettings,
    image_config: ImageBackendConfig,
    brief: StaticCreativeInput,
) -> int:
    if settings.database_url is None:
        raise FixtureError("PostgreSQL image run requires AIC_AI_DATABASE_URL")
    storage_settings = settings.object_storage()
    if storage_settings.backend != "s3":
        raise FixtureError("PostgreSQL image run requires shared S3 object storage")

    database = Database(settings.database_url.get_secret_value())
    try:
        await database.check()
        repository = PostgresCreativeRepository(database.engine)
        object_storage = storage_settings.build()
        await asyncio.to_thread(object_storage.check)
        artifact_service = ArtifactService(
            PostgresArtifactCatalog(database.engine),
            object_storage,
            storage_settings.bucket,
        )
        runtime = build_runtime(
            None,
            settings.data_root / "artifacts",
            args.config,
            image_config=image_config,
            image_api_key=settings.credential(image_config.api_key_env or image_config.token_env),
            product_segmenter_config=(
                load_product_segmenter_config(product_segmenter_config_path)
                if (
                    product_segmenter_config_path := getattr(
                        settings, "product_segmenter_config", None
                    )
                )
                else None
            ),
            image_brief=brief,
            seed=args.seed,
            repository=repository,
            usage_tracker=AIUsageTracker(PostgresAIUsageRepository(database.engine)),
        )
        work_item = load_work_item(args.fixture)
        outcome = await runtime.run(work_item)
        job = outcome.result.job
        if job is None:
            logger.error("Run produced no job: {}", outcome.result.error)
            return 1

        root = runtime.artifact_store.root.resolve()
        for version in job.versions:
            if version.artifact_path is None:
                continue
            image_path = Path(version.artifact_path).resolve()
            await artifact_service.publish_file(
                image_path,
                image_path.relative_to(root).as_posix(),
                kind=ArtifactKind.GENERATED,
                owner_type="creative",
                owner_id=job.job_id.value,
            )
            version_dir = image_path.parent
            for review_path in (version_dir / "review.json", *(version_dir / "inputs").glob("*")):
                if review_path.is_file():
                    await artifact_service.publish_file(
                        review_path,
                        review_path.relative_to(root).as_posix(),
                        kind=ArtifactKind.SOURCE,
                        owner_type="creative",
                        owner_id=job.job_id.value,
                    )

        manifest = runtime.run_dir(work_item.source_run_id) / "manifest.json"
        print_job(job, str(manifest) if manifest.exists() else None)
        _write_line(f"Dashboard:    /dashboard/creatives/{job.job_id.value}")
        if not outcome.result.success:
            logger.error(
                "Run ended in exception: {} ({})",
                outcome.result.exception_type,
                outcome.result.error,
            )
            return 1
        return 0
    finally:
        await database.close()


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
    if args.command in {
        "run-creative-loop",
        "decide-creative-loop",
        "record-creative-loop-ads-outcome",
        "inspect-creative-loop",
    }:
        if (args.fixture is None) == (args.local_loop is None):
            raise ValueError("Use exactly one of --fixture or --local-loop")
        image_config_path = getattr(args, "image_config", None)
        review_config_path = getattr(args, "review_config", None)
        image_config = load_image_config(image_config_path) if image_config_path else None
        review_config = (
            load_semantic_reviewer_config(review_config_path) if review_config_path else None
        )
        product_segmenter_config_path = getattr(settings, "product_segmenter_config", None)
        product_segmenter_config = (
            load_product_segmenter_config(product_segmenter_config_path)
            if product_segmenter_config_path
            else None
        )
        learning_config_path = getattr(args, "learning_config", None)
        learning_config = (
            load_performance_learning_config(learning_config_path) if learning_config_path else None
        )
        preparation_config = (
            getattr(args, "preparation_config", None) or args.config / "preparation/synthetic.json"
        )
        runtime = build_creative_loop_runtime(
            args.db,
            args.artifacts,
            config_dir=args.config,
            fixture_path=args.fixture,
            local_loop_path=args.local_loop,
            preparation_config=preparation_config,
            preparation_api_key=settings.credential(
                load_preparation_config(preparation_config).api_key_env
            ),
            image_config=image_config,
            image_api_key=(
                settings.credential(image_config.api_key_env or image_config.token_env)
                if image_config
                else None
            ),
            product_segmenter_config=product_segmenter_config,
            review_config=review_config,
            review_api_key=(
                settings.credential(review_config.api_key_env) if review_config else None
            ),
            learning_config=learning_config,
            learning_api_key=(
                settings.credential(learning_config.api_key_env) if learning_config else None
            ),
        )
        try:
            if args.command == "run-creative-loop":
                outcome = await runtime.run()
                for run in outcome.runs:
                    _write_line(f"{run.run_id:40} {run.state.value}")
                _write_line(f"Runs:          {len(outcome.runs)}")
                _write_line(f"Duplicates:    {outcome.duplicate_count}")
                _write_line(
                    "External writes: disabled; model mode: "
                    + (
                        "configured"
                        if image_config or review_config or learning_config
                        else "synthetic"
                    )
                )
                return 0
            run = await runtime.repository.get(args.run_id)
            if run is None:
                raise ValueError("Creative loop run not found")
            if args.command == "inspect-creative-loop":
                _write_line(f"Run:           {run.run_id}")
                _write_line(f"State:         {run.state.value}")
                _write_line(f"Creative:      {run.approved_creative_version_id or 'pending'}")
                _write_line(f"Ads event:     {run.ads_event_id or 'pending'}")
                _write_line(f"Lesson:        {run.lesson_id or 'pending'}")
                _write_line(f"Next brief:    {run.next_creative_job_id or 'pending'}")
                return 0
            if args.command == "record-creative-loop-ads-outcome":
                if run.approved_creative_version_id is None:
                    raise ValueError("Creative loop has no approved Creative version")
                updated = await runtime.record_ads_outcome(
                    run.run_id,
                    replace(
                        runtime.fixture.ads_outcome(run.input_snapshot_id),
                        creative_version_id=run.approved_creative_version_id,
                    ),
                )
            elif args.gate == "demand":
                if not args.pinned_id:
                    raise ValueError("--pinned-id must be the exact H2 evaluation ID")
                updated = await runtime.decide_demand(
                    run.run_id,
                    args.pinned_id,
                    PerformanceDecision(args.decision),
                    args.reviewer,
                    args.reason,
                )
            elif args.gate == "creative":
                if args.decision == "defer":
                    raise ValueError("Creative gate supports approve or reject")
                updated = await runtime.decide_creative(
                    run.run_id,
                    ApprovalDecision(args.decision),
                    args.reviewer,
                    args.reason,
                )
            else:
                if not args.pinned_id:
                    raise ValueError("--pinned-id must be the exact X1 lesson ID")
                updated = await runtime.decide_lesson(
                    run.run_id,
                    args.pinned_id,
                    FeedbackDecision(args.decision),
                    args.reviewer,
                    args.reason,
                    args.learning_proposal_id,
                )
            _write_line(f"Run:           {updated.run_id}")
            _write_line(f"State:         {updated.state.value}")
            return 0
        finally:
            runtime.close()
    if args.command == "run-creative-intake":
        fixture = load_creative_intake_fixture(args.fixture)
        source_options = (args.source, args.source_run_id, args.context_snapshot_id)
        if any(source_options) and not all(source_options):
            raise ValueError(
                "--source, --source-run-id and --context-snapshot-id must be provided together"
            )
        if all(source_options):
            if args.source == "performance":
                source_runtime = build_performance_decision_read_runtime(args.db, args.artifacts)
                try:
                    source_run = await source_runtime.repository.get(args.source_run_id)
                    if source_run is None:
                        source_run = await source_runtime.repository.get_by_source_run_id(
                            args.source_run_id
                        )
                    if source_run is None:
                        raise ValueError("Performance source run not found")
                    trigger = project_performance_trigger(source_run)
                finally:
                    source_runtime.repository.close()
            else:
                source_runtime = build_creative_feedback_read_runtime(args.db, args.artifacts)
                try:
                    source_run = await source_runtime.repository.get(args.source_run_id)
                    if source_run is None:
                        source_run = await source_runtime.repository.get_by_source_run_id(
                            args.source_run_id
                        )
                    if source_run is None:
                        raise ValueError("Creative feedback source run not found")
                    trigger = project_feedback_trigger(source_run)
                finally:
                    source_runtime.repository.close()
            if not trigger.source_released:
                raise ValueError("The selected upstream preview has not been approved and released")
            fixture = CreativeIntakeFixture(
                (case_for_trigger(fixture, args.context_snapshot_id, trigger),)
            )
        runtime = build_creative_intake_runtime(args.db, args.artifacts)
        try:
            outcome = await runtime.run(
                fixture,
                dispatch_m1=args.dispatch_m1,
                dispatch_creative=args.dispatch_creative,
                preparation_config=args.preparation_config,
                config_dir=args.config,
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
    if args.command == "run-creative-feedback":
        fixture = load_creative_feedback_fixture(args.fixture)
        learning_config = (
            load_performance_learning_config(args.learning_config)
            if args.learning_config is not None
            else None
        )
        runtime = build_creative_feedback_runtime(
            args.db,
            args.artifacts,
            learning_config=learning_config,
            learning_api_key=(
                settings.credential(learning_config.api_key_env) if learning_config else None
            ),
        )
        try:
            outcome = await runtime.run(fixture)
            for run in outcome.runs:
                _write_line(
                    f"{run.release.creative_version_id:28} "
                    f"{run.performance.classification.value:24} {run.state.value}"
                )
            _write_line(f"Runs:          {len(outcome.runs)}")
            _write_line(f"Duplicates:    {outcome.duplicate_count}")
            _write_line("External write: disabled")
            return 0
        finally:
            runtime.repository.close()
    if args.command == "run-performance-decision":
        fixture = load_performance_decision_fixture(args.fixture)
        opportunity_config = (
            load_opportunity_config(args.opportunity_config)
            if args.opportunity_config is not None
            else None
        )
        runtime = build_performance_decision_runtime(
            args.db,
            args.artifacts,
            opportunity_config=opportunity_config,
            opportunity_api_key=(
                settings.credential(opportunity_config.api_key_env)
                if opportunity_config is not None
                else None
            ),
        )
        try:
            outcome = await runtime.run(fixture)
            for run in outcome.runs:
                _write_line(
                    f"{run.snapshot.subject.subject_type.value:10} "
                    f"{run.snapshot.subject.subject_id:24} "
                    f"{run.evaluation.classification.value:30} "
                    f"{run.evaluation.state.value}"
                )
                if run.opportunity_analysis is not None:
                    _write_line(
                        f"  Agent shadow: {run.opportunity_analysis.category.value} "
                        f"priority={run.opportunity_analysis.priority}"
                    )
            _write_line(f"Runs:          {len(outcome.runs)}")
            _write_line(f"Duplicates:    {outcome.duplicate_count}")
            _write_line("External write: disabled")
            return 0
        finally:
            runtime.repository.close()
    if args.command == "run-gmc-ingestion":
        fixture = load_gmc_fixture(args.fixture)
        runtime = build_gmc_runtime(args.db, args.artifacts, fixture)
        try:
            outcome = await runtime.run(fixture)
            run = outcome.run
            _write_line(f"Run:          {run.run_id}")
            _write_line(f"Status:       {run.status.value}")
            _write_line(f"Source:       {run.source.source_ref}")
            _write_line(f"Rows:         {run.total_rows}")
            _write_line(f"Accepted:     {run.accepted_rows}")
            _write_line(f"Rejected:     {run.rejected_rows}")
            _write_line(f"Matched:      {run.matched_rows}")
            _write_line(f"GMC-only:     {run.gmc_only_rows}")
            _write_line(f"Conflicts:    {run.conflicting_rows}")
            _write_line(f"Duplicates:   {run.duplicate_rows}")
            if outcome.duplicate:
                _write_line("Duplicate trigger: existing run returned")
            if run.normalized_artifact_ref:
                _write_line(f"Normalized:   {run.normalized_artifact_ref}")
            if run.rejected_artifact_ref:
                _write_line(f"Rejected:     {run.rejected_artifact_ref}")
            return 0 if run.status.value != "blocked" else 1
        finally:
            runtime.repository.close()
    if args.command == "prepare-brief":
        config = load_preparation_config(args.preparation_config)
        case = _load_cli_preparation_case(
            args,
            max_context_bytes=config.max_context_bytes,
        )
        runtime = build_preparation_runtime(
            args.db,
            args.artifacts,
            config,
            case.context,
            api_key=settings.credential(config.api_key_env),
            config_dir=args.config,
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
    if args.command == "run-marketing-video":
        config_path = args.video_config or settings.video_config
        if config_path is None:
            raise ValueError("--video-config or AIC_AI_VIDEO_CONFIG is required")
        config = load_video_config(config_path)
        result = await run_video_marketing(
            load_video_marketing_plan(args.plan),
            config,
            build_video_backend(config, api_key=settings.credential(config.api_key_env)),
            args.output,
        )
        for final_path in result.final_paths or (result.final_path,):
            _write_line(f"Video awaiting human review: {final_path.resolve()}")
        _write_line(f"Manifest: {result.manifest_path.resolve()}")
        return 0
    if args.command == "review-marketing-video":
        review_path = review_video_marketing(args.run_dir, args.decision, args.reason)
        _write_line(f"Review: {review_path.resolve()}")
        return 0
    if args.command == "generate-video":
        config_path = args.video_config or settings.video_config
        if config_path is None:
            raise ValueError(
                "--video-config or AIC_AI_VIDEO_CONFIG is required for video generation"
            )
        config = load_video_config(config_path)
        output = await generate_video_clip(
            config,
            VideoGenerationRequest(
                prompt=args.prompt,
                seconds=args.seconds,
                size=args.size,
                quality=args.quality,
            ),
            args.output,
            api_key=settings.credential(config.api_key_env),
        )
        _write_line(f"Video: {output.resolve()}")
        _write_line(f"Metadata: {(args.output / 'metadata.json').resolve()}")
        return 0
    if args.command == "init-image-eval":
        initialize_image_example(args.output)
        _write_line(f"Synthetic dataset created: {args.output.resolve()}")
        return 0
    if args.command == "benchmark-images":
        run_dir = await benchmark_images(
            args.dataset,
            args.image_config,
            args.output,
            args.seed,
            args.case,
            settings.credential,
        )
        _write_line(f"Results: {run_dir}")
        _write_line(f"Blind review: {run_dir / 'review' / 'index.html'}")
        results = read_evaluation_results(run_dir)
        return (
            0
            if all(item.status == "completed" and item.technical_passed for item in results)
            else 1
        )
    if args.command == "review-image":
        if bool(args.criteria) != bool(args.rubric_version):
            raise ValueError("--criteria and --rubric-version must be provided together")
        if args.criteria and not args.rubric:
            raise ValueError("--rubric is required with --criteria")
        rubric = load_review_rubric(args.rubric) if args.rubric else None
        path = record_image_review(
            args.run_dir,
            HumanImageReview(
                sample_id=args.sample,
                decision=args.decision,
                reviewer=args.reviewer,
                reason=args.reason,
                critical_product_error=args.critical_product_error,
                rubric_version=args.rubric_version,
                criteria=(load_human_criterion_reviews(args.criteria) if args.criteria else []),
            ),
            rubric,
        )
        _write_line(f"Review recorded: {path}")
        return 0
    if args.command == "report-images":
        rubric = load_review_rubric(args.rubric) if args.rubric else None
        summarize_image_evaluation(args.run_dir, rubric)
        _write_line(f"Summary: {args.run_dir / 'summary.json'}")
        return 0
    if args.command == "validate-golden-dataset":
        report = assess_golden_dataset(args.dataset, load_review_rubric(args.rubric))
        _write_line(report.model_dump_json(indent=2))
        return 0 if report.status == "ready" else 1
    if args.command == "audit-static-lineage":
        rows = build_static_lineage_crosswalk(
            args.manifest, args.dataset, load_review_rubric(args.rubric)
        )
        write_static_lineage_crosswalk(rows, args.output)
        _write_line(f"Historical Static crosswalk: {args.output.resolve()} ({len(rows)} rows)")
        return 0
    if args.command == "prepare-golden-review":
        output = prepare_historical_review_pack(
            args.dataset, load_review_rubric(args.rubric), args.output
        )
        _write_line(f"Historical review pack: {output / 'review' / 'index.html'}")
        _write_line(f"Review template: {output / 'review-template.json'}")
        return 0
    if args.command == "review-golden-image":
        rubric = load_review_rubric(args.rubric)
        path = record_historical_review(
            args.dataset,
            args.review_pack,
            args.sample,
            HistoricalHumanReview(
                decision=args.decision,
                reviewer_alias=args.reviewer,
                reason=args.reason,
                critical_product_error=args.critical_product_error,
                rubric_version=rubric.ref,
                criteria=load_human_criterion_reviews(args.criteria),
            ),
            rubric,
        )
        _write_line(f"Historical review recorded: {path}")
        return 0
    image_config = None
    brief = None
    if args.command == "run":
        options = (args.image_config, args.image_dataset, args.case)
        if any(options) and not all(options):
            raise FixtureError("Image run needs --image-config, --image-dataset and --case")
        if all(options):
            if not 0 <= args.seed < 2**32:
                raise FixtureError("Seed must be an unsigned 32-bit integer")
            image_config = load_image_config(args.image_config)
            dataset = load_image_dataset(args.image_dataset)
            case = next((case for case in dataset.cases if case.case_id == args.case), None)
            if case is None:
                raise FixtureError("Selected case does not exist in image dataset")
            brief = case.input
    if settings.database_backend == "postgresql" and args.command == "run":
        if image_config is None or brief is None:
            raise FixtureError("PostgreSQL run requires an image config, dataset and case")
        return await _cmd_run_postgres_image(args, settings, image_config, brief)

    runtime = build_runtime(
        args.db,
        args.artifacts,
        args.config,
        image_config=image_config,
        image_api_key=(
            settings.credential(image_config.api_key_env or image_config.token_env)
            if image_config is not None
            else None
        ),
        product_segmenter_config=(
            load_product_segmenter_config(product_segmenter_config_path)
            if (
                product_segmenter_config_path := getattr(settings, "product_segmenter_config", None)
            )
            else None
        ),
        image_brief=brief,
        seed=getattr(args, "seed", 0),
    )
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
    except (PreparationError, ConfigError) as e:
        logger.error("Preparation/configuration error: {}", e)
        return 1
    except ValidationError:
        logger.error("Invalid configuration/input/review; check schema and required fields")
        return 1
    except ImageGenerationError as e:
        logger.error("Image pilot error: {}", e)
        return 1
    except VideoGenerationError as e:
        logger.error("Video pilot error: {}", e)
        return 1
    except InputDriftError as e:
        logger.error("Input drift: {}", e)
        return 1
    except PerformanceInputDriftError as e:
        logger.error("Performance input drift: {}", e)
        return 1
    except CreativeFeedbackInputDriftError as e:
        logger.error("Creative feedback input drift: {}", e)
        return 1
    except CreativeIntakeInputDriftError as e:
        logger.error("Creative intake input drift: {}", e)
        return 1
    except (CreativeLoopInputDriftError, CreativeLoopEventDriftError) as e:
        logger.error("Creative loop input/event drift: {}", e)
        return 1
    except OSError as e:
        logger.error("Pilot storage error: {}", e)
        return 1
    except ValueError as e:
        logger.error("Pilot input error: {}", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
