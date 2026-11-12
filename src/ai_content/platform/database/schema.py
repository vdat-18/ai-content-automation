"""SQLAlchemy Core metadata for current persisted application state."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
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


marketplace_products = Table(
    "marketplace_products",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("title", Text),
    Column("sold_count", BigInteger),
    Column("has_video", Boolean, nullable=False, server_default=sql_text("false")),
    Column("listing", JSONB),
    Column("detail", JSONB),
    Column("detail_captured_at", DateTime(timezone=True)),
    Column("deleted", Boolean, nullable=False, server_default=sql_text("false")),
    *_timestamps(),
    schema="marketing",
)

product_selections = Table(
    "product_selections",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("product_type", Text),
    *_timestamps(),
    schema="marketing",
)

reference_profiles = Table(
    "reference_profiles",
    metadata,
    Column("product_type", Text, primary_key=True),
    Column("keywords", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default=sql_text("'draft'")),
    *_timestamps(),
    schema="marketing",
)

product_briefs = Table(
    "product_briefs",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("user_idea", Text, nullable=False, server_default=sql_text("''")),
    Column("brief", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default=sql_text("'draft'")),
    *_timestamps(),
    schema="marketing",
)

product_keyframes = Table(
    "product_keyframes",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("shot_index", Integer, primary_key=True),
    Column("status", Text, nullable=False),
    Column("prompt", Text, nullable=False, server_default=sql_text("''")),
    Column("image_path", Text),
    Column("attempts", Integer, nullable=False, server_default=sql_text("0")),
    Column("error", Text),
    Column("qa_problem", Text, nullable=False, server_default=sql_text("''")),
    *_timestamps(),
    schema="marketing",
)

product_clips = Table(
    "product_clips",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("shot_index", Integer, primary_key=True),
    Column("status", Text, nullable=False),
    Column("job_id", Text),
    Column("job_model", Text),
    Column("video_path", Text),
    Column("seconds", Integer, nullable=False, server_default=sql_text("0")),
    Column("attempts", Integer, nullable=False, server_default=sql_text("0")),
    Column("error", Text),
    Column("qa_problem", Text, nullable=False, server_default=sql_text("''")),
    *_timestamps(),
    schema="marketing",
)

product_pipeline_runs = Table(
    "product_pipeline_runs",
    metadata,
    Column("product_id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("message", Text, nullable=False, server_default=sql_text("''")),
    *_timestamps(),
    schema="marketing",
)

product_events = Table(
    "product_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("product_id", Text, nullable=False),
    Column("step", Text, nullable=False),
    Column("shot_index", Integer),
    Column("status", Text, nullable=False),
    Column("message", Text, nullable=False, server_default=sql_text("''")),
    Column("at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    schema="marketing",
)
Index("ix_product_events_product", product_events.c.product_id, product_events.c.id)

reference_images = Table(
    "reference_images",
    metadata,
    Column("image_id", Text, primary_key=True),
    Column("product_type", Text, nullable=False),
    Column("query", Text, nullable=False),
    Column("image_url", Text, nullable=False),
    Column("pin_url", Text),
    Column("title", Text),
    Column("status", Text, nullable=False, server_default=sql_text("'pending'")),
    Column("screening", JSONB),
    Column("phash", Text),
    Column("embedding", JSONB),
    Column("text_embedding", JSONB),
    Column("duplicate_of", Text),
    *_timestamps(),
    schema="marketing",
)

reference_searches = Table(
    "reference_searches",
    metadata,
    Column("product_type", Text, primary_key=True),
    Column("query", Text, primary_key=True),
    *_timestamps(),
    schema="marketing",
)

creative_knowledge = Table(
    "creative_knowledge",
    metadata,
    Column("knowledge_id", Text, primary_key=True),
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
    CheckConstraint(
        "status IN ('draft', 'proposed', 'approved', 'rejected', 'expired', 'conflict')",
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
    creative_knowledge.c.brand_id,
    creative_knowledge.c.niche_id,
    creative_knowledge.c.product_archetype,
    creative_knowledge.c.product_family_id,
    creative_knowledge.c.variant_id,
)
Index(
    "ix_creative_knowledge_status_type",
    creative_knowledge.c.status,
    creative_knowledge.c.knowledge_type,
)

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

__all__ = [
    "marketplace_products",
    "product_selections",
    "product_briefs",
    "product_clips",
    "product_events",
    "product_keyframes",
    "product_pipeline_runs",
    "reference_images",
    "reference_profiles",
    "reference_searches",
    "ai_usage_events",
    "artifacts",
    "metadata",
    "notifications",
]
