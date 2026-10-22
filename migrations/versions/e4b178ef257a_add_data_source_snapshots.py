"""Add read-only data source snapshot metadata.

Revision ID: e4b178ef257a
Revises: 50e9e9ed3b6b
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4b178ef257a"
down_revision: str | None = "50e9e9ed3b6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_source_snapshots",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("artifact_ref", sa.Text(), nullable=False),
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
            "record_count >= 0", name=op.f("ck_data_source_snapshots_nonnegative_record_count")
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name=op.f("pk_data_source_snapshots")),
        sa.UniqueConstraint(
            "source_id", "checksum_sha256", name=op.f("uq_data_source_snapshots_source_id")
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_data_source_snapshots_source",
        "data_source_snapshots",
        ["source_id"],
        schema="marketing",
    )
    op.create_table(
        "data_source_sync_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
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
            "status IN ('succeeded', 'failed')",
            name=op.f("ck_data_source_sync_runs_valid_data_source_sync_status"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_data_source_sync_runs")),
        schema="marketing",
    )
    op.create_index(
        "ix_data_source_sync_runs_source",
        "data_source_sync_runs",
        ["source_id"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_source_sync_runs_source", table_name="data_source_sync_runs", schema="marketing"
    )
    op.drop_table("data_source_sync_runs", schema="marketing")
    op.drop_index(
        "ix_data_source_snapshots_source", table_name="data_source_snapshots", schema="marketing"
    )
    op.drop_table("data_source_snapshots", schema="marketing")
