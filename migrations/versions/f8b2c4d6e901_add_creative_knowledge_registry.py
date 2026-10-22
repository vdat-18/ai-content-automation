"""add Creative knowledge registry

Revision ID: f8b2c4d6e901
Revises: e5a4b9c8d712
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8b2c4d6e901"
down_revision: str | None = "e5a4b9c8d712"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_knowledge_versions",
        sa.Column("knowledge_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("knowledge_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Text()),
        sa.Column("niche_id", sa.Text()),
        sa.Column("product_family_id", sa.Text()),
        sa.Column("variant_id", sa.Text()),
        sa.Column("platform", sa.Text()),
        sa.Column("market", sa.Text()),
        sa.Column("asset_type", sa.Text()),
        sa.Column("task_type", sa.Text()),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint("version > 0", name="positive_creative_knowledge_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'proposed', 'approved', 'rejected', 'superseded', 'expired', 'conflict')",
            name="valid_creative_knowledge_status",
        ),
        sa.PrimaryKeyConstraint("knowledge_id", "version"),
        schema="marketing",
    )
    op.create_index(
        "ix_creative_knowledge_scope",
        "creative_knowledge_versions",
        ["brand_id", "niche_id", "product_family_id", "variant_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_creative_knowledge_status_type",
        "creative_knowledge_versions",
        ["status", "knowledge_type"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creative_knowledge_status_type",
        table_name="creative_knowledge_versions",
        schema="marketing",
    )
    op.drop_index(
        "ix_creative_knowledge_scope",
        table_name="creative_knowledge_versions",
        schema="marketing",
    )
    op.drop_table("creative_knowledge_versions", schema="marketing")
