"""investigations + public observations

Revision ID: 0005_investigations
Revises: 0004_public_bot_referrals
Create Date: 2026-09-05 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_investigations"
down_revision: str | None = "0004_public_bot_referrals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_normalized", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("report_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_investigation_user_id_user"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_investigation_job_id_job"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["report.id"],
            name=op.f("fk_investigation_report_id_report"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigation")),
    )
    with op.batch_alter_table("investigation", schema=None) as batch_op:
        batch_op.create_index("ix_investigation_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_investigation_public_id", ["public_id"], unique=True)
        batch_op.create_index(
            "ix_investigation_target_normalized", ["target_normalized"], unique=False
        )
        batch_op.create_index("ix_investigation_status", ["status"], unique=False)
        batch_op.create_index("ix_investigation_created_at", ["created_at"], unique=False)

    op.create_table(
        "investigation_observation",
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("observation_type", sa.String(length=16), nullable=False),
        sa.Column("resource_kind", sa.String(length=16), nullable=False),
        sa.Column("resource_ref", sa.String(length=255), nullable=False),
        sa.Column("resource_url", sa.String(length=1024), nullable=True),
        sa.Column("message_ref", sa.String(length=64), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigation.id"],
            name=op.f("fk_investigation_observation_investigation_id_investigation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigation_observation")),
    )
    with op.batch_alter_table("investigation_observation", schema=None) as batch_op:
        batch_op.create_index(
            "ix_investigation_observation_investigation_id", ["investigation_id"], unique=False
        )
        batch_op.create_index(
            "ix_investigation_observation_type", ["observation_type"], unique=False
        )
        batch_op.create_index(
            "ix_investigation_observation_observed_at", ["observed_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("investigation_observation", schema=None) as batch_op:
        batch_op.drop_index("ix_investigation_observation_observed_at")
        batch_op.drop_index("ix_investigation_observation_type")
        batch_op.drop_index("ix_investigation_observation_investigation_id")
    op.drop_table("investigation_observation")

    with op.batch_alter_table("investigation", schema=None) as batch_op:
        batch_op.drop_index("ix_investigation_created_at")
        batch_op.drop_index("ix_investigation_status")
        batch_op.drop_index("ix_investigation_target_normalized")
        batch_op.drop_index("ix_investigation_public_id")
        batch_op.drop_index("ix_investigation_user_id")
    op.drop_table("investigation")
