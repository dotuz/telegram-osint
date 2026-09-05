"""public bot tier: free-action counter + referrer

Revision ID: 0004_public_bot_referrals
Revises: 0003_refresh_tokens
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_public_bot_referrals"
down_revision: str | None = "0003_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("free_actions_used", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("invited_by_telegram_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("invited_by_telegram_id")
        batch_op.drop_column("free_actions_used")
