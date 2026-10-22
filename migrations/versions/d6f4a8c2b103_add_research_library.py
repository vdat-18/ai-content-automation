"""add canonical research library records

Revision ID: d6f4a8c2b103
Revises: b4e8c2d7f901
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6f4a8c2b103"
down_revision: str | None = "b4e8c2d7f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_crawl_jobs",
        sa.Column("crawl_fingerprint", sa.Text(), nullable=True),
        schema="marketing",
    )
    op.create_index(
        "uq_research_crawl_jobs_active_fingerprint",
        "research_crawl_jobs",
        ["crawl_fingerprint"],
        unique=True,
        schema="marketing",
        postgresql_where=sa.text(
            "crawl_fingerprint IS NOT NULL AND status IN ('queued', 'pending', 'running', 'retry_wait')"
        ),
    )
    op.create_table(
        "research_records",
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("record_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("advertiser", sa.Text(), nullable=True),
        sa.Column("destination_domain", sa.Text(), nullable=True),
        sa.Column("has_images", sa.Boolean(), nullable=False),
        sa.Column("has_videos", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("latest_run_id", sa.Text(), nullable=False),
        sa.Column("version_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["latest_run_id"], ["marketing.research_crawl_jobs.job_id"]),
        sa.PrimaryKeyConstraint("record_key"),
        sa.UniqueConstraint("workspace_id", "brand_id", "platform", "external_id"),
        schema="marketing",
    )
    op.create_index(
        "ix_research_records_scope_seen",
        "research_records",
        ["workspace_id", "brand_id", "last_seen_at"],
        schema="marketing",
    )
    op.create_index(
        "ix_research_records_platform", "research_records", ["platform"], schema="marketing"
    )
    op.create_index(
        "ix_research_records_status", "research_records", ["status"], schema="marketing"
    )
    op.create_table(
        "research_record_versions",
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["marketing.research_crawl_jobs.job_id"]),
        sa.ForeignKeyConstraint(
            ["record_key"], ["marketing.research_records.record_key"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("record_key", "content_hash"),
        schema="marketing",
    )
    op.create_index(
        "ix_research_record_versions_record",
        "research_record_versions",
        ["record_key", "observed_at"],
        schema="marketing",
    )
    op.create_table(
        "research_run_records",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('new', 'updated', 'unchanged')",
            name=op.f("ck_research_run_records_valid_research_record_disposition"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["marketing.research_crawl_jobs.job_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["record_key"], ["marketing.research_records.record_key"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", "record_key"),
        schema="marketing",
    )
    op.create_index(
        "ix_research_run_records_record", "research_run_records", ["record_key"], schema="marketing"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_run_records_record", table_name="research_run_records", schema="marketing"
    )
    op.drop_table("research_run_records", schema="marketing")
    op.drop_index(
        "ix_research_record_versions_record",
        table_name="research_record_versions",
        schema="marketing",
    )
    op.drop_table("research_record_versions", schema="marketing")
    op.drop_index("ix_research_records_status", table_name="research_records", schema="marketing")
    op.drop_index("ix_research_records_platform", table_name="research_records", schema="marketing")
    op.drop_index(
        "ix_research_records_scope_seen", table_name="research_records", schema="marketing"
    )
    op.drop_table("research_records", schema="marketing")
    op.drop_index(
        "uq_research_crawl_jobs_active_fingerprint",
        table_name="research_crawl_jobs",
        schema="marketing",
    )
    op.drop_column("research_crawl_jobs", "crawl_fingerprint", schema="marketing")
