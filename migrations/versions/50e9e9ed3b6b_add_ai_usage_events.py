"""Add durable AI usage events.

Revision ID: 50e9e9ed3b6b
Revises: c1f4c51c2c8a
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "50e9e9ed3b6b"
down_revision: str | None = "c1f4c51c2c8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("workstream", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("output_count", sa.Integer()),
        sa.Column("output_bytes", sa.BigInteger()),
        sa.Column("cost_amount", sa.Numeric(20, 8)),
        sa.Column("cost_currency", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("source_run_id", sa.Text()),
        sa.Column("workflow_run_id", sa.Text()),
        sa.Column("job_id", sa.Text()),
        sa.Column("version_id", sa.Text()),
        sa.Column("brand_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name=op.f("ck_ai_usage_events_valid_ai_usage_status"),
        ),
        sa.CheckConstraint(
            "request_count >= 0", name=op.f("ck_ai_usage_events_nonnegative_ai_request_count")
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_ai_usage_events_nonnegative_ai_input_tokens"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_ai_usage_events_nonnegative_ai_output_tokens"),
        ),
        sa.CheckConstraint(
            "output_count IS NULL OR output_count >= 0",
            name=op.f("ck_ai_usage_events_nonnegative_ai_output_count"),
        ),
        sa.CheckConstraint(
            "output_bytes IS NULL OR output_bytes >= 0",
            name=op.f("ck_ai_usage_events_nonnegative_ai_output_bytes"),
        ),
        sa.CheckConstraint(
            "cost_amount IS NULL OR cost_amount >= 0",
            name=op.f("ck_ai_usage_events_nonnegative_ai_cost"),
        ),
        sa.CheckConstraint(
            "(cost_amount IS NULL) = (cost_currency IS NULL)",
            name=op.f("ck_ai_usage_events_complete_ai_cost"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_ai_usage_events")),
        schema="platform",
    )
    for name, columns in (
        ("ix_ai_usage_events_started_at", ["started_at"]),
        ("ix_ai_usage_events_workstream_time", ["workstream", "started_at"]),
        ("ix_ai_usage_events_model_time", ["model", "started_at"]),
        ("ix_ai_usage_events_workflow", ["workflow_run_id"]),
        ("ix_ai_usage_events_job", ["job_id"]),
        ("ix_ai_usage_events_status", ["status"]),
    ):
        op.create_index(name, "ai_usage_events", columns, schema="platform")


def downgrade() -> None:
    for name in (
        "ix_ai_usage_events_status",
        "ix_ai_usage_events_job",
        "ix_ai_usage_events_workflow",
        "ix_ai_usage_events_model_time",
        "ix_ai_usage_events_workstream_time",
        "ix_ai_usage_events_started_at",
    ):
        op.drop_index(name, table_name="ai_usage_events", schema="platform")
    op.drop_table("ai_usage_events", schema="platform")
