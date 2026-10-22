"""Expand AI usage traceability and run-level reporting.

Revision ID: e5a4b9c8d712
Revises: d6f4a8c2b103
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a4b9c8d712"
down_revision: str | None = "d6f4a8c2b103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_usage_events", sa.Column("batch_id", sa.Text()), schema="platform")
    op.add_column("ai_usage_events", sa.Column("run_id", sa.Text()), schema="platform")
    op.add_column("ai_usage_events", sa.Column("parent_event_id", sa.Text()), schema="platform")
    op.add_column("ai_usage_events", sa.Column("attempt_number", sa.Integer()), schema="platform")
    op.add_column(
        "ai_usage_events", sa.Column("provider_request_id", sa.Text()), schema="platform"
    )
    op.create_check_constraint(
        "ck_ai_usage_events_positive_attempt_number",
        "ai_usage_events",
        "attempt_number IS NULL OR attempt_number > 0",
        schema="platform",
    )
    op.execute(
        """
        UPDATE platform.ai_usage_events
        SET run_id = COALESCE(workflow_run_id, job_id, source_run_id, version_id)
        WHERE run_id IS NULL
        """
    )
    op.create_index("ix_ai_usage_events_batch", "ai_usage_events", ["batch_id"], schema="platform")
    op.create_index(
        "ix_ai_usage_events_run",
        "ai_usage_events",
        ["run_id", "started_at"],
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_run", table_name="ai_usage_events", schema="platform")
    op.drop_index("ix_ai_usage_events_batch", table_name="ai_usage_events", schema="platform")
    op.drop_constraint(
        "ck_ai_usage_events_positive_attempt_number",
        "ai_usage_events",
        schema="platform",
    )
    op.drop_column("ai_usage_events", "provider_request_id", schema="platform")
    op.drop_column("ai_usage_events", "attempt_number", schema="platform")
    op.drop_column("ai_usage_events", "parent_event_id", schema="platform")
    op.drop_column("ai_usage_events", "run_id", schema="platform")
    op.drop_column("ai_usage_events", "batch_id", schema="platform")
