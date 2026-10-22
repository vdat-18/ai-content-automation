"""Add an indexed product catalog read model.

Revision ID: fe5a6b7c8d9e
Revises: fd4e5f6a7b8c
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe5a6b7c8d9e"
down_revision: str | None = "fd4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_source_product_catalog",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["marketing.data_source_snapshots.snapshot_id"],
            name=op.f("fk_data_source_product_catalog_snapshot_id_data_source_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            "provider_id",
            name=op.f("pk_data_source_product_catalog"),
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_data_source_product_catalog_source_snapshot",
        "data_source_product_catalog",
        ["source_id", "snapshot_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_data_source_product_catalog_sort",
        "data_source_product_catalog",
        ["brand", "title", "provider_id"],
        schema="marketing",
    )
    op.execute(
        """
        INSERT INTO marketing.data_source_product_catalog (
            snapshot_id,
            source_id,
            provider_id,
            brand,
            title,
            search_text,
            data
        )
        SELECT
            snapshot.snapshot_id,
            snapshot.source_id,
            record.item ->> 'provider_id',
            COALESCE(record.item -> 'data' ->> 'brand', ''),
            COALESCE(
                record.item -> 'data' ->> 'title',
                record.item -> 'data' ->> 'family_key',
                record.item -> 'data' ->> 'sku',
                record.item -> 'data' ->> 'handle',
                record.item ->> 'provider_id'
            ),
            lower(concat_ws(
                ' ',
                record.item -> 'data' ->> 'family_key',
                record.item -> 'data' ->> 'title',
                record.item -> 'data' ->> 'handle',
                variant_skus.value,
                variants.value
            )),
            record.item -> 'data'
        FROM marketing.data_source_snapshots AS snapshot
        CROSS JOIN LATERAL jsonb_array_elements(snapshot.payload -> 'records') AS record(item)
        LEFT JOIN LATERAL (
            SELECT string_agg(sku.value, ' ') AS value
            FROM jsonb_array_elements_text(
                COALESCE(record.item -> 'data' -> 'variant_skus', '[]'::jsonb)
            ) AS sku(value)
        ) AS variant_skus ON true
        LEFT JOIN LATERAL (
            SELECT string_agg(
                concat_ws(' ', variant.item ->> 'sku', variant.item ->> 'title'),
                ' '
            ) AS value
            FROM jsonb_array_elements(
                COALESCE(record.item -> 'data' -> 'variants', '[]'::jsonb)
            ) AS variant(item)
        ) AS variants ON true
        WHERE snapshot.provider = 'shopify'
          AND record.item ->> 'kind' = 'product'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_source_product_catalog_sort",
        table_name="data_source_product_catalog",
        schema="marketing",
    )
    op.drop_index(
        "ix_data_source_product_catalog_source_snapshot",
        table_name="data_source_product_catalog",
        schema="marketing",
    )
    op.drop_table("data_source_product_catalog", schema="marketing")
