"""Replace DBOS dispatch with a transactional Celery outbox.

Revision ID: a9d4e2f6b731
Revises: f7c9d2e4a611
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e2f6b731"
down_revision: str | None = "f7c9d2e4a611"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_outbox",
        sa.Column("outbox_id", sa.Text(), nullable=False),
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("queue_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
            "attempts >= 0",
            name=op.f("ck_execution_outbox_nonnegative_attempts"),
        ),
        sa.CheckConstraint(
            "dispatch_generation >= 0",
            name=op.f("ck_execution_outbox_nonnegative_dispatch_generation"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published')",
            name=op.f("ck_execution_outbox_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["platform.execution_commands.command_id"],
            name=op.f("fk_execution_outbox_command_id_execution_commands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("outbox_id", name=op.f("pk_execution_outbox")),
        sa.UniqueConstraint(
            "command_id",
            "dispatch_generation",
            name=op.f("uq_execution_outbox_command_id"),
        ),
        schema="platform",
    )
    op.create_index(
        "ix_execution_outbox_ready",
        "execution_outbox",
        ["status", "available_at"],
        unique=False,
        schema="platform",
    )
    op.execute(
        """
        UPDATE platform.execution_commands
        SET status = 'failed',
            updated_at = CURRENT_TIMESTAMP,
            available_at = CURRENT_TIMESTAMP,
            last_error_code = 'EXECUTION_BACKEND_CUTOVER',
            last_error_message =
                'Command stopped during the Celery cutover; retry it to create a Celery task',
            audit_log = audit_log || jsonb_build_array(
                'celery_cutover_failed:' || CURRENT_TIMESTAMP::text
            )
        WHERE execution_backend = 'dbos'
          AND status IN ('pending', 'running', 'retry_wait', 'cancel_requested')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_outbox_ready",
        table_name="execution_outbox",
        schema="platform",
    )
    op.drop_table("execution_outbox", schema="platform")
