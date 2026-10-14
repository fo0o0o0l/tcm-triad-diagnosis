"""create reports

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 复用既有 PG 原生枚举，禁止重复 CREATE TYPE（create_type=False）
health_level = postgresql.ENUM(
    "good", "fair", "poor", "bad", name="health_level", create_type=False
)
# report_status 为本迁移新增：显式 CREATE TYPE 一次；建表时引用 create_type=False 的同名枚举，
# 避免 SQLAlchemy 在 create_table 阶段再次 CREATE TYPE 造成 “already exists”
report_status = postgresql.ENUM(
    "draft", "final", "archived", name="report_status", create_type=True
)
report_status_col = postgresql.ENUM(
    "draft", "final", "archived", name="report_status", create_type=False
)


def upgrade() -> None:
    report_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("fusion_id", sa.BigInteger(), nullable=True),
        sa.Column("status", report_status_col, server_default="draft", nullable=False),
        sa.Column(
            "patient_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("overall_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("health_level", health_level, nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=True),
        sa.Column(
            "report_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("pdf_ref", sa.String(length=255), nullable=True),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["fusion_id"], ["fusion_results.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_no"),
    )
    op.create_index("ix_reports_session_id", "reports", ["session_id"], unique=False)
    op.create_index(
        "idx_reports_session", "reports", ["session_id", "generated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_reports_session", table_name="reports")
    op.drop_index("ix_reports_session_id", table_name="reports")
    op.drop_table("reports")
    report_status.drop(op.get_bind(), checkfirst=True)