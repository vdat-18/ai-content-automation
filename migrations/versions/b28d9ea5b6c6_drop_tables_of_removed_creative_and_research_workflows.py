"""Drop tables of the removed Shopify creative, data source, research and execution workflows.

Revision ID: b28d9ea5b6c6
Revises: b17c8d9ea5b5
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b28d9ea5b6c6"
down_revision: str | None = "b17c8d9ea5b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMOVED_TABLES = (
    "creative_jobs",
    "creative_versions",
    "marketing_creative_automation_states",
    "creative_intake_runs",
    "creative_automation_batches",
    "creative_automation_jobs",
    "creative_automation_states",
    "creative_automation_events",
    "research_crawl_jobs",
    "research_records",
    "research_run_records",
    "research_reference_products",
    "research_reference_uses",
    "gmc_ingestion_runs",
    "media_lab_assets",
    "data_source_snapshots",
    "data_source_product_catalog",
    "data_source_sync_runs",
)


REMOVED_PLATFORM_TABLES = ("execution_outbox", "execution_commands")


def upgrade() -> None:
    for table in REMOVED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS marketing.{table} CASCADE")
    for table in REMOVED_PLATFORM_TABLES:
        op.execute(f"DROP TABLE IF EXISTS platform.{table} CASCADE")


def downgrade() -> None:
    raise NotImplementedError("Dropped workflow tables are not restored")
