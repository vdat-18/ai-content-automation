"""add artifact catalog

Revision ID: c1f4c51c2c8a
Revises: 9bf6bf184e81
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1f4c51c2c8a"
down_revision: str | None = "9bf6bf184e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("retention_class", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("brand_scope", sa.Text(), nullable=True),
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
            "kind IN ('source', 'generated', 'evaluation', 'projection', 'temporary')",
            name=op.f("ck_artifacts_valid_kind"),
        ),
        sa.CheckConstraint(
            "retention_class IN ('standard', 'temporary')",
            name=op.f("ck_artifacts_valid_retention_class"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_artifacts_nonnegative_size_bytes")),
        sa.CheckConstraint(
            "status IN ('pending', 'available', 'failed')",
            name=op.f("ck_artifacts_valid_status"),
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("object_key", name=op.f("uq_artifacts_object_key")),
        schema="platform",
    )
    op.create_index(
        "ix_artifacts_source_path",
        "artifacts",
        ["source_path", "updated_at"],
        unique=False,
        schema="platform",
    )
    op.create_index(
        "ix_artifacts_status",
        "artifacts",
        ["status"],
        unique=False,
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index("ix_artifacts_status", table_name="artifacts", schema="platform")
    op.drop_index("ix_artifacts_source_path", table_name="artifacts", schema="platform")
    op.drop_table("artifacts", schema="platform")
