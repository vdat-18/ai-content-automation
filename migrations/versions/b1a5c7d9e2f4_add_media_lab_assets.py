"""Add reusable Media Lab asset metadata.

Revision ID: b1a5c7d9e2f4
Revises: 8e53b3a4c0d1
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1a5c7d9e2f4"
down_revision: str | None = "8e53b3a4c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_assets",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("media_kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Text(), nullable=True),
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
            "media_kind IN ('image', 'video')",
            name=op.f("ck_media_lab_assets_valid_media_lab_asset_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'ready', 'failed')",
            name=op.f("ck_media_lab_assets_valid_media_lab_asset_state"),
        ),
        sa.CheckConstraint(
            "origin IN ('upload', 'media_lab_image_output', 'media_lab_video_output')",
            name=op.f("ck_media_lab_assets_valid_media_lab_asset_origin"),
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_media_lab_assets")),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_assets_checksum",
        "media_lab_assets",
        ["checksum_sha256"],
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_assets_source_run",
        "media_lab_assets",
        ["source_run_id"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_assets_source_run",
        table_name="media_lab_assets",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_assets_checksum",
        table_name="media_lab_assets",
        schema="marketing",
    )
    op.drop_table("media_lab_assets", schema="marketing")
