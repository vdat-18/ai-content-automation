"""Store Creative knowledge as one editable row per item.

Revision ID: ab2c3d4e5f60
Revises: aa1b2c3d4e5f
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ab2c3d4e5f60"
down_revision: str | None = "aa1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "marketing.creative_knowledge_versions"


def upgrade() -> None:
    # Keep the approved version of each item, or its latest one when none is approved.
    op.execute(
        f"""
        DELETE FROM {_TABLE} v
        WHERE v.version <> (
            SELECT COALESCE(MAX(w.version) FILTER (WHERE w.status = 'approved'), MAX(w.version))
            FROM {_TABLE} w
            WHERE w.knowledge_id = v.knowledge_id
        )
        """
    )
    op.execute(
        f"""
        UPDATE {_TABLE}
        SET status = 'expired',
            payload = jsonb_set(payload, '{{status}}', '"expired"')
        WHERE status = 'superseded'
        """
    )
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = '{_TABLE}'::regclass AND contype IN ('p', 'c')
            LOOP
                EXECUTE format('ALTER TABLE {_TABLE} DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$
        """
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN version")
    op.execute(f"UPDATE {_TABLE} SET payload = (payload - 'version') - 'supersedes'")
    op.execute(f"ALTER TABLE {_TABLE} RENAME TO creative_knowledge")
    op.execute(
        "ALTER TABLE marketing.creative_knowledge "
        "ADD CONSTRAINT pk_creative_knowledge PRIMARY KEY (knowledge_id)"
    )
    op.execute(
        "ALTER TABLE marketing.creative_knowledge "
        "ADD CONSTRAINT ck_creative_knowledge_valid_creative_knowledge_status "
        "CHECK (status IN ('draft', 'proposed', 'approved', 'rejected', 'expired', 'conflict'))"
    )


def downgrade() -> None:
    raise NotImplementedError("Collapsed knowledge history is not restored")
