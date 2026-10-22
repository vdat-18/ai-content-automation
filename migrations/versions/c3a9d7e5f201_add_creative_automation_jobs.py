"""add durable Creative automation jobs and notifications

Revision ID: c3a9d7e5f201
Revises: a9d4e2f6b731
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3a9d7e5f201"
down_revision: str | None = "d2c8a4f9e731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_automation_batches",
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("batch_id", name=op.f("pk_creative_automation_batches")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_creative_automation_batches_idempotency_key")
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_batches_created",
        "creative_automation_batches",
        ["created_at"],
        schema="marketing",
    )
    op.create_table(
        "creative_automation_jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("execution_mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("command_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "execution_mode IN ('brief_only', 'generate_once')",
            name=op.f("ck_creative_automation_jobs_valid_creative_automation_execution_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["marketing.creative_automation_batches.batch_id"],
            name=op.f("fk_creative_automation_jobs_batch_id_creative_automation_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_creative_automation_jobs")),
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_jobs_batch",
        "creative_automation_jobs",
        ["batch_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_jobs_status",
        "creative_automation_jobs",
        ["status"],
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_jobs_scope",
        "creative_automation_jobs",
        ["brand_id", "market", "created_at"],
        schema="marketing",
    )
    op.create_table(
        "creative_automation_states",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_creative_automation_states_valid_creative_automation_state_revision"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["marketing.creative_automation_jobs.job_id"],
            name=op.f("fk_creative_automation_states_request_id_creative_automation_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_id", name=op.f("pk_creative_automation_states")),
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_states_status",
        "creative_automation_states",
        ["status"],
        schema="marketing",
    )
    op.create_table(
        "creative_automation_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["marketing.creative_automation_jobs.job_id"],
            name=op.f("fk_creative_automation_events_job_id_creative_automation_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_creative_automation_events")),
        schema="marketing",
    )
    op.create_index(
        "ix_creative_automation_events_job",
        "creative_automation_events",
        ["job_id", "created_at"],
        schema="marketing",
    )
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("action_path", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("notification_id", name=op.f("pk_notifications")),
        schema="platform",
    )
    op.create_index(
        "ix_notifications_scope", "notifications", ["scope_type", "scope_id"], schema="platform"
    )
    op.create_index(
        "ix_notifications_unread", "notifications", ["read_at", "created_at"], schema="platform"
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_unread", table_name="notifications", schema="platform")
    op.drop_index("ix_notifications_scope", table_name="notifications", schema="platform")
    op.drop_table("notifications", schema="platform")
    op.drop_index(
        "ix_creative_automation_events_job",
        table_name="creative_automation_events",
        schema="marketing",
    )
    op.drop_table("creative_automation_events", schema="marketing")
    op.drop_index(
        "ix_creative_automation_states_status",
        table_name="creative_automation_states",
        schema="marketing",
    )
    op.drop_table("creative_automation_states", schema="marketing")
    op.drop_index(
        "ix_creative_automation_jobs_scope",
        table_name="creative_automation_jobs",
        schema="marketing",
    )
    op.drop_index(
        "ix_creative_automation_jobs_status",
        table_name="creative_automation_jobs",
        schema="marketing",
    )
    op.drop_index(
        "ix_creative_automation_jobs_batch",
        table_name="creative_automation_jobs",
        schema="marketing",
    )
    op.drop_table("creative_automation_jobs", schema="marketing")
    op.drop_index(
        "ix_creative_automation_batches_created",
        table_name="creative_automation_batches",
        schema="marketing",
    )
    op.drop_table("creative_automation_batches", schema="marketing")
