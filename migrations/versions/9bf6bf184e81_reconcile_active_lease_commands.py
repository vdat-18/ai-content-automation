"""Reconcile active lease commands before the DBOS production cutover.

Revision ID: 9bf6bf184e81
Revises: 6d9b2cb4a617
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9bf6bf184e81"
down_revision: str | None = "6d9b2cb4a617"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE platform.execution_commands
        SET status = 'failed',
            updated_at = CURRENT_TIMESTAMP,
            available_at = CURRENT_TIMESTAMP,
            lease_owner = NULL,
            lease_expires_at = NULL,
            last_error_code = 'EXECUTION_BACKEND_CUTOVER',
            last_error_message =
                'Command stopped during the DBOS cutover; retry it to create a DBOS execution',
            audit_log = audit_log || jsonb_build_array(
                'backend_cutover_failed:' || CURRENT_TIMESTAMP::text
            )
        WHERE execution_backend = 'lease_worker'
          AND status IN ('pending', 'running', 'retry_wait')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE platform.execution_commands
        SET status = 'pending',
            updated_at = CURRENT_TIMESTAMP,
            available_at = CURRENT_TIMESTAMP,
            max_attempts = GREATEST(max_attempts, attempts + 1),
            last_error_code = NULL,
            last_error_message = NULL,
            audit_log = audit_log || jsonb_build_array(
                'backend_cutover_rollback:' || CURRENT_TIMESTAMP::text
            )
        WHERE execution_backend = 'lease_worker'
          AND status = 'failed'
          AND last_error_code = 'EXECUTION_BACKEND_CUTOVER'
        """
    )
