"""add public research crawl jobs

Revision ID: b4e8c2d7f901
Revises: c3a9d7e5f201
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e8c2d7f901"
down_revision: str | None = "c3a9d7e5f201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_crawl_jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
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
            "status IN ('queued', 'pending', 'running', 'retry_wait', 'completed', 'failed')",
            name=op.f("ck_research_crawl_jobs_valid_research_crawl_status"),
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_research_crawl_jobs")),
        schema="marketing",
    )
    op.create_index(
        "ix_research_crawl_jobs_created",
        "research_crawl_jobs",
        ["created_at"],
        schema="marketing",
    )
    op.create_index(
        "ix_research_crawl_jobs_scope",
        "research_crawl_jobs",
        ["workspace_id", "brand_id", "created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_crawl_jobs_scope",
        table_name="research_crawl_jobs",
        schema="marketing",
    )
    op.drop_index(
        "ix_research_crawl_jobs_created",
        table_name="research_crawl_jobs",
        schema="marketing",
    )
    op.drop_table("research_crawl_jobs", schema="marketing")
