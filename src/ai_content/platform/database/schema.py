"""SQLAlchemy Core metadata for current persisted application state."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _timestamps() -> tuple[Column[DateTime], Column[DateTime]]:
    return (
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


creative_jobs = Table(
    "creative_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    UniqueConstraint("source_run_id"),
    schema="marketing",
)

creative_versions = Table(
    "creative_versions",
    metadata,
    Column("version_id", Text, primary_key=True),
    Column(
        "job_id",
        Text,
        ForeignKey("marketing.creative_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("attempt_number", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    UniqueConstraint("job_id", "attempt_number"),
    CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
    schema="marketing",
)

marketing_creative_automation_states = Table(
    "marketing_creative_automation_states",
    metadata,
    Column("request_id", Text, primary_key=True),
    Column("package_id", Text, nullable=False),
    Column("package_ref", Text, nullable=False),
    Column("route", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("route IN ('manual', 'assisted', 'automated')", name="valid_route"),
    CheckConstraint("revision >= 0", name="nonnegative_revision"),
    schema="marketing",
)
Index(
    "ix_marketing_creative_automation_states_status",
    marketing_creative_automation_states.c.status,
    marketing_creative_automation_states.c.updated_at,
)


def _run_table(name: str, *columns: Column[object]) -> Table:
    return Table(
        name,
        metadata,
        Column("run_id", Text, primary_key=True),
        Column("source_run_id", Text, nullable=False, unique=True),
        *columns,
        Column("payload", JSONB, nullable=False),
        *_timestamps(),
        schema="marketing",
    )


creative_loop_runs = _run_table(
    "creative_loop_runs",
    Column("source_checksum", Text, nullable=False),
    Column("state", Text, nullable=False),
)
creative_intake_runs = _run_table(
    "creative_intake_runs",
    Column("source_checksum", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("brand_id", Text, nullable=False),
    Column("sku_id", Text, nullable=False),
)
creative_feedback_runs = _run_table(
    "creative_feedback_runs",
    Column("source_checksum", Text, nullable=False),
    Column("creative_version_id", Text, nullable=False),
    Column("state", Text, nullable=False),
)

creative_knowledge_versions = Table(
    "creative_knowledge_versions",
    metadata,
    Column("knowledge_id", Text, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("knowledge_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("authority", Text, nullable=False),
    Column("brand_id", Text),
    Column("niche_id", Text),
    Column("product_archetype", Text),
    Column("product_family_id", Text),
    Column("variant_id", Text),
    Column("platform", Text),
    Column("market", Text),
    Column("asset_type", Text),
    Column("task_type", Text),
    Column("effective_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("version > 0", name="positive_creative_knowledge_version"),
    CheckConstraint(
        "status IN ('draft', 'proposed', 'approved', 'rejected', 'superseded', 'expired', 'conflict')",
        name="valid_creative_knowledge_status",
    ),
    schema="marketing",
)

creative_knowledge_bootstraps = Table(
    "creative_knowledge_bootstraps",
    metadata,
    Column("bootstrap_id", Text, primary_key=True),
    Column("schema_version", Text, nullable=False),
    Column("checksum", Text, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("applied_by", Text, nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("item_count > 0", name="positive_creative_knowledge_bootstrap_items"),
    schema="marketing",
)
Index(
    "ix_creative_knowledge_scope",
    creative_knowledge_versions.c.brand_id,
    creative_knowledge_versions.c.niche_id,
    creative_knowledge_versions.c.product_archetype,
    creative_knowledge_versions.c.product_family_id,
    creative_knowledge_versions.c.variant_id,
)
Index(
    "ix_creative_knowledge_status_type",
    creative_knowledge_versions.c.status,
    creative_knowledge_versions.c.knowledge_type,
)

creative_automation_batches = Table(
    "creative_automation_batches",
    metadata,
    Column("batch_id", Text, primary_key=True),
    Column("idempotency_key", Text, nullable=True, unique=True),
    Column("brand_id", Text, nullable=False),
    Column("requested_by", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    schema="marketing",
)
Index("ix_creative_automation_batches_created", creative_automation_batches.c.created_at)

creative_automation_jobs = Table(
    "creative_automation_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column(
        "batch_id",
        Text,
        ForeignKey("marketing.creative_automation_batches.batch_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sku_id", Text, nullable=False),
    Column("brand_id", Text, nullable=False),
    Column("market", Text, nullable=False),
    Column("execution_mode", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("command_id", Text),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "execution_mode IN ('brief_only', 'generate_once')",
        name="valid_creative_automation_execution_mode",
    ),
    schema="marketing",
)
Index("ix_creative_automation_jobs_batch", creative_automation_jobs.c.batch_id)
Index("ix_creative_automation_jobs_status", creative_automation_jobs.c.status)
Index(
    "ix_creative_automation_jobs_scope",
    creative_automation_jobs.c.brand_id,
    creative_automation_jobs.c.market,
    creative_automation_jobs.c.created_at,
)

creative_automation_states = Table(
    "creative_automation_states",
    metadata,
    Column(
        "request_id",
        Text,
        ForeignKey("marketing.creative_automation_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("status", Text, nullable=False),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("revision >= 0", name="valid_creative_automation_state_revision"),
    schema="marketing",
)
Index("ix_creative_automation_states_status", creative_automation_states.c.status)

creative_automation_events = Table(
    "creative_automation_events",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column(
        "job_id",
        Text,
        ForeignKey("marketing.creative_automation_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="marketing",
)
Index(
    "ix_creative_automation_events_job",
    creative_automation_events.c.job_id,
    creative_automation_events.c.created_at,
)

research_crawl_jobs = Table(
    "research_crawl_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("workspace_id", Text, nullable=False),
    Column("brand_id", Text, nullable=False),
    Column("project_id", Text),
    Column("source_url", Text, nullable=False),
    Column("crawl_fingerprint", Text),
    Column("status", Text, nullable=False),
    Column("command_id", Text),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "status IN ('queued', 'pending', 'running', 'retry_wait', 'completed', 'failed')",
        name="valid_research_crawl_status",
    ),
    schema="marketing",
)
Index("ix_research_crawl_jobs_created", research_crawl_jobs.c.created_at)
Index(
    "uq_research_crawl_jobs_active_fingerprint",
    research_crawl_jobs.c.crawl_fingerprint,
    unique=True,
    postgresql_where=sql_text(
        "crawl_fingerprint IS NOT NULL AND status IN ('queued', 'pending', 'running', 'retry_wait')"
    ),
)
Index(
    "ix_research_crawl_jobs_scope",
    research_crawl_jobs.c.workspace_id,
    research_crawl_jobs.c.brand_id,
    research_crawl_jobs.c.created_at,
)

research_records = Table(
    "research_records",
    metadata,
    Column("record_key", Text, primary_key=True),
    Column("workspace_id", Text, nullable=False),
    Column("brand_id", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("record_type", Text, nullable=False),
    Column("title", Text),
    Column("text", Text, nullable=False),
    Column("status", Text),
    Column("advertiser", Text),
    Column("destination_domain", Text),
    Column("screening_status", Text, nullable=False, server_default=sql_text("'kept'")),
    Column("review_status", Text, nullable=False, server_default="pending_review"),
    Column("reviewer_alias", Text),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("review_reason", Text),
    Column("deleted_at", DateTime(timezone=True)),
    Column("has_images", Boolean, nullable=False),
    Column("has_videos", Boolean, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "latest_run_id", Text, ForeignKey("marketing.research_crawl_jobs.job_id"), nullable=False
    ),
    Column("version_count", Integer, nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "screening_status IN ('kept', 'auto_filtered', 'unavailable')",
        name="valid_research_screening_status",
    ),
    UniqueConstraint("workspace_id", "brand_id", "platform", "external_id"),
    schema="marketing",
)
Index(
    "ix_research_records_scope_seen",
    research_records.c.workspace_id,
    research_records.c.brand_id,
    research_records.c.last_seen_at,
)
Index("ix_research_records_platform", research_records.c.platform)
Index("ix_research_records_status", research_records.c.status)
Index("ix_research_records_review_status", research_records.c.review_status)
Index("ix_research_records_screening_status", research_records.c.screening_status)

research_record_versions = Table(
    "research_record_versions",
    metadata,
    Column("version_id", Text, primary_key=True),
    Column(
        "record_key",
        Text,
        ForeignKey("marketing.research_records.record_key", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("job_id", Text, ForeignKey("marketing.research_crawl_jobs.job_id"), nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("record_key", "content_hash"),
    schema="marketing",
)
Index(
    "ix_research_record_versions_record",
    research_record_versions.c.record_key,
    research_record_versions.c.observed_at,
)

research_run_records = Table(
    "research_run_records",
    metadata,
    Column(
        "job_id",
        Text,
        ForeignKey("marketing.research_crawl_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "record_key",
        Text,
        ForeignKey("marketing.research_records.record_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("disposition", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "disposition IN ('new', 'updated', 'unchanged')", name="valid_research_record_disposition"
    ),
    schema="marketing",
)
Index("ix_research_run_records_record", research_run_records.c.record_key)

notifications = Table(
    "notifications",
    metadata,
    Column("notification_id", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("scope_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("detail", Text, nullable=False),
    Column("action_path", Text),
    Column("read_at", DateTime(timezone=True)),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    schema="platform",
)
Index("ix_notifications_scope", notifications.c.scope_type, notifications.c.scope_id)
Index("ix_notifications_unread", notifications.c.read_at, notifications.c.created_at)
performance_decision_runs = _run_table(
    "performance_decision_runs",
    Column("source_checksum", Text, nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
)
gmc_ingestion_runs = _run_table(
    "gmc_ingestion_runs",
    Column("source_checksum", Text, nullable=False),
    Column("status", Text, nullable=False),
)
email_health_runs = _run_table(
    "email_health_runs",
    Column("source_checksum", Text, nullable=False),
    Column("issue_fingerprint", Text, nullable=False),
    Column("account_id", Text, nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
)
Index("ix_email_health_runs_issue_fingerprint", email_health_runs.c.issue_fingerprint)
creator_evaluation_runs = _run_table(
    "creator_evaluation_runs",
    Column("candidate_id", Text, nullable=False, unique=True),
    Column("source_checksum", Text, nullable=False),
)
creator_outreach_runs = _run_table(
    "creator_outreach_runs",
    Column("candidate_id", Text, nullable=False),
    Column("state", Text, nullable=False),
)

media_lab_image_runs = Table(
    "media_lab_image_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("generation_state", Text, nullable=False),
    Column("review_state", Text, nullable=False),
    Column("intent", Text, nullable=False),
    Column("backend_run_id", Text),
    Column("parent_run_id", Text),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "generation_state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
        name="valid_media_lab_image_generation_state",
    ),
    CheckConstraint(
        "review_state IN ('not_ready', 'awaiting_human_review', 'approved', 'rejected')",
        name="valid_media_lab_image_review_state",
    ),
    schema="marketing",
)
Index("ix_media_lab_image_runs_backend", media_lab_image_runs.c.backend_run_id)
Index("ix_media_lab_image_runs_created", media_lab_image_runs.c.created_at)

media_lab_video_runs = Table(
    "media_lab_video_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("generation_state", Text, nullable=False),
    Column("review_state", Text, nullable=False),
    Column("intent", Text, nullable=False),
    Column("backend_run_id", Text),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "generation_state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
        name="valid_media_lab_video_generation_state",
    ),
    CheckConstraint(
        "review_state IN ('not_ready', 'awaiting_human_review', 'approved', 'rejected')",
        name="valid_media_lab_video_review_state",
    ),
    schema="marketing",
)
Index("ix_media_lab_video_runs_backend", media_lab_video_runs.c.backend_run_id)
Index("ix_media_lab_video_runs_created", media_lab_video_runs.c.created_at)

media_lab_video_projects = Table(
    "media_lab_video_projects",
    metadata,
    Column("project_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "state IN ('assembling', 'awaiting_human_review', 'approved', 'rejected', 'failed')",
        name="valid_media_lab_video_project_state",
    ),
    schema="marketing",
)
Index("ix_media_lab_video_projects_state", media_lab_video_projects.c.state)
Index("ix_media_lab_video_projects_created", media_lab_video_projects.c.created_at)

media_lab_video_ad_jobs = Table(
    "media_lab_video_ad_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "state IN ('planning', 'needs_input', 'generating_shots', "
        "'selecting_segments', 'assembling', 'completed', 'failed', "
        "'cancel_requested', 'cancelled')",
        name="valid_media_lab_video_ad_job_state",
    ),
    schema="marketing",
)
Index("ix_media_lab_video_ad_jobs_state", media_lab_video_ad_jobs.c.state)
Index("ix_media_lab_video_ad_jobs_created", media_lab_video_ad_jobs.c.created_at)

media_lab_planning_jobs = Table(
    "media_lab_planning_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint(
        "state IN ('planning', 'ready', 'needs_input', 'failed')",
        name="valid_media_lab_planning_job_state",
    ),
    schema="marketing",
)
Index("ix_media_lab_planning_jobs_state", media_lab_planning_jobs.c.state)
Index("ix_media_lab_planning_jobs_created", media_lab_planning_jobs.c.created_at)


media_lab_assets = Table(
    "media_lab_assets",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("media_kind", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("checksum_sha256", Text, nullable=False),
    Column("source_run_id", Text),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("media_kind IN ('image', 'video')", name="valid_media_lab_asset_kind"),
    CheckConstraint(
        "state IN ('processing', 'ready', 'failed')", name="valid_media_lab_asset_state"
    ),
    CheckConstraint(
        "origin IN ('upload', 'media_lab_image_output', 'media_lab_video_output')",
        name="valid_media_lab_asset_origin",
    ),
    schema="marketing",
)
Index("ix_media_lab_assets_checksum", media_lab_assets.c.checksum_sha256)
Index("ix_media_lab_assets_source_run", media_lab_assets.c.source_run_id)

email_reports = Table(
    "email_reports",
    metadata,
    Column("report_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    schema="marketing",
)

email_production_jobs = Table(
    "email_production_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("source_run_id", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    schema="marketing",
)

execution_commands = Table(
    "execution_commands",
    metadata,
    Column("command_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("dedupe_key", Text, nullable=False, unique=True),
    Column("payload_checksum", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("workflow_run_id", Text),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("last_error_code", Text),
    Column("last_error_message", Text),
    Column("completed_at", DateTime(timezone=True)),
    Column("execution_backend", Text, nullable=False, server_default="lease_worker"),
    Column("queue_name", Text, nullable=False, server_default="control"),
    Column("dispatch_generation", Integer, nullable=False, server_default="0"),
    Column("execution_id", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("cancel_requested_at", DateTime(timezone=True)),
    Column("cancelled_at", DateTime(timezone=True)),
    Column("audit_log", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
    CheckConstraint("max_attempts > 0", name="positive_max_attempts"),
    CheckConstraint("dispatch_generation >= 0", name="nonnegative_dispatch_generation"),
    schema="platform",
)
Index(
    "ix_execution_commands_ready",
    execution_commands.c.status,
    execution_commands.c.available_at,
)

execution_outbox = Table(
    "execution_outbox",
    metadata,
    Column("outbox_id", Text, primary_key=True),
    Column(
        "command_id",
        Text,
        ForeignKey("platform.execution_commands.command_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("dispatch_generation", Integer, nullable=False),
    Column("task_name", Text, nullable=False),
    Column("queue_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
    Column("last_error_message", Text),
    *_timestamps(),
    UniqueConstraint("command_id", "dispatch_generation"),
    CheckConstraint("dispatch_generation >= 0", name="nonnegative_dispatch_generation"),
    CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
    CheckConstraint(
        "status IN ('pending', 'publishing', 'published')",
        name="valid_status",
    ),
    schema="platform",
)
Index(
    "ix_execution_outbox_ready",
    execution_outbox.c.status,
    execution_outbox.c.available_at,
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", Text, primary_key=True),
    Column("bucket", Text, nullable=False),
    Column("object_key", Text, nullable=False, unique=True),
    Column("source_path", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("retention_class", Text, nullable=False),
    Column("owner_type", Text, nullable=False),
    Column("owner_id", Text, nullable=False),
    Column("brand_scope", Text),
    *_timestamps(),
    CheckConstraint("size_bytes >= 0", name="nonnegative_size_bytes"),
    CheckConstraint(
        "kind IN ('source', 'generated', 'evaluation', 'projection', 'temporary')",
        name="valid_kind",
    ),
    CheckConstraint(
        "status IN ('pending', 'available', 'failed')",
        name="valid_status",
    ),
    CheckConstraint(
        "retention_class IN ('standard', 'temporary')",
        name="valid_retention_class",
    ),
    schema="platform",
)
Index("ix_artifacts_source_path", artifacts.c.source_path, artifacts.c.updated_at)
Index("ix_artifacts_status", artifacts.c.status)
Index(
    "ix_execution_commands_workflow",
    execution_commands.c.workflow_run_id,
    execution_commands.c.created_at,
)

ai_usage_events = Table(
    "ai_usage_events",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("workstream", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("backend", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("model_revision", Text),
    Column("status", Text, nullable=False),
    Column("request_count", Integer, nullable=False, server_default="0"),
    Column("input_tokens", BigInteger),
    Column("output_tokens", BigInteger),
    Column("output_count", Integer),
    Column("output_bytes", BigInteger),
    Column("cost_amount", Numeric(20, 8)),
    Column("cost_currency", Text),
    Column("error_code", Text),
    Column("source_run_id", Text),
    Column("workflow_run_id", Text),
    Column("job_id", Text),
    Column("version_id", Text),
    Column("brand_id", Text),
    Column("batch_id", Text),
    Column("run_id", Text),
    Column("parent_event_id", Text),
    Column("attempt_number", Integer),
    Column("provider_request_id", Text),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("duration_ms", BigInteger),
    CheckConstraint(
        "status IN ('started', 'succeeded', 'failed')",
        name="valid_ai_usage_status",
    ),
    CheckConstraint("request_count >= 0", name="nonnegative_ai_request_count"),
    CheckConstraint(
        "input_tokens IS NULL OR input_tokens >= 0", name="nonnegative_ai_input_tokens"
    ),
    CheckConstraint(
        "output_tokens IS NULL OR output_tokens >= 0", name="nonnegative_ai_output_tokens"
    ),
    CheckConstraint(
        "output_count IS NULL OR output_count >= 0", name="nonnegative_ai_output_count"
    ),
    CheckConstraint(
        "output_bytes IS NULL OR output_bytes >= 0", name="nonnegative_ai_output_bytes"
    ),
    CheckConstraint("cost_amount IS NULL OR cost_amount >= 0", name="nonnegative_ai_cost"),
    CheckConstraint(
        "(cost_amount IS NULL) = (cost_currency IS NULL)",
        name="complete_ai_cost",
    ),
    schema="platform",
)
Index("ix_ai_usage_events_started_at", ai_usage_events.c.started_at)
Index(
    "ix_ai_usage_events_workstream_time", ai_usage_events.c.workstream, ai_usage_events.c.started_at
)
Index("ix_ai_usage_events_model_time", ai_usage_events.c.model, ai_usage_events.c.started_at)
Index("ix_ai_usage_events_workflow", ai_usage_events.c.workflow_run_id)
Index("ix_ai_usage_events_job", ai_usage_events.c.job_id)
Index("ix_ai_usage_events_batch", ai_usage_events.c.batch_id)
Index("ix_ai_usage_events_run", ai_usage_events.c.run_id, ai_usage_events.c.started_at)
Index("ix_ai_usage_events_status", ai_usage_events.c.status)

data_source_snapshots = Table(
    "data_source_snapshots",
    metadata,
    Column("snapshot_id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("checksum_sha256", Text, nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("artifact_ref", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    UniqueConstraint("source_id", "checksum_sha256"),
    CheckConstraint("record_count >= 0", name="nonnegative_record_count"),
    schema="marketing",
)
Index("ix_data_source_snapshots_source", data_source_snapshots.c.source_id)

data_source_product_catalog = Table(
    "data_source_product_catalog",
    metadata,
    Column(
        "snapshot_id",
        Text,
        ForeignKey("marketing.data_source_snapshots.snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("source_id", Text, nullable=False),
    Column("provider_id", Text, primary_key=True),
    Column("brand", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("search_text", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    schema="marketing",
)
Index(
    "ix_data_source_product_catalog_source_snapshot",
    data_source_product_catalog.c.source_id,
    data_source_product_catalog.c.snapshot_id,
)
Index(
    "ix_data_source_product_catalog_sort",
    data_source_product_catalog.c.brand,
    data_source_product_catalog.c.title,
    data_source_product_catalog.c.provider_id,
)

data_source_sync_runs = Table(
    "data_source_sync_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    *_timestamps(),
    CheckConstraint("status IN ('succeeded', 'failed')", name="valid_data_source_sync_status"),
    schema="marketing",
)
Index("ix_data_source_sync_runs_source", data_source_sync_runs.c.source_id)


__all__ = [
    "ai_usage_events",
    "artifacts",
    "creative_feedback_runs",
    "creative_automation_batches",
    "creative_automation_events",
    "creative_automation_jobs",
    "creative_automation_states",
    "creative_intake_runs",
    "creative_jobs",
    "creative_loop_runs",
    "creative_versions",
    "data_source_snapshots",
    "data_source_product_catalog",
    "data_source_sync_runs",
    "creator_evaluation_runs",
    "creator_outreach_runs",
    "email_health_runs",
    "email_production_jobs",
    "email_reports",
    "execution_commands",
    "gmc_ingestion_runs",
    "media_lab_assets",
    "media_lab_image_runs",
    "media_lab_planning_jobs",
    "media_lab_video_runs",
    "media_lab_video_projects",
    "media_lab_video_ad_jobs",
    "marketing_creative_automation_states",
    "metadata",
    "notifications",
    "performance_decision_runs",
    "research_crawl_jobs",
    "research_records",
    "research_record_versions",
    "research_run_records",
]
