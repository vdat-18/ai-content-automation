"""Add the general everyday-scene reference profile.

Product types without pictures of their own use these scenes.

Revision ID: b17c8d9e0fa5
Revises: a1e5c7d9f2b4
Create Date: 2026-11-12
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b17c8d9e0fa5"
down_revision: str | None = "a1e5c7d9f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPE = "cảnh đời thường chung"
_KEYWORDS = [
    "person holding product at home candid lifestyle photo",
    "woman showing product in kitchen natural light",
    "person unboxing product on bed cozy room",
    "man using product at desk casual lifestyle",
    "người cầm sản phẩm review tự nhiên",
    "small rented room window light lifestyle photo",
    "girl talking to camera at home selfie style",
    "everyday life product demo phone camera look",
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO marketing.reference_profiles (product_type, keywords, status) "
            "VALUES (:product_type, CAST(:keywords AS jsonb), 'approved') "
            "ON CONFLICT (product_type) DO NOTHING"
        ).bindparams(product_type=_TYPE, keywords=json.dumps(_KEYWORDS, ensure_ascii=False))
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM marketing.reference_profiles WHERE product_type = :product_type")
        .bindparams(product_type=_TYPE)
    )
