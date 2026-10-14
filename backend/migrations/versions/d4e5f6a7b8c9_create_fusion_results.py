"""create fusion results

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 复用舌诊迁移已创建的 PG 原生枚举，禁止重复 CREATE TYPE（create_type=False）
analysis_status = postgresql.ENUM(
    "pending", "analyzing", "completed", "failed", name="analysis_status", create_type=False
)
# health_level 为本迁移新增：显式 CREATE TYPE 一次；建表时引用 create_type=False 的同名枚举，
# 避免 SQLAlchemy 在 create_table 阶段再次 CREATE TYPE 造成 “already exists”
health_level = postgresql.ENUM(
    "good",
    "fair",
    "poor",
    "bad",
    name="health_level",
    create_type=True,
)
health_level_col = postgresql.ENUM(
    "good",
    "fair",
    "poor",
    "bad",
    name="health_level",
    create_type=False,
)


def upgrade() -> None:
    health_level.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "fusion_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fusion_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("status", analysis_status, server_default="pending", nullable=False),
        sa.Column("overall_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("health_level", health_level_col, nullable=True),
        sa.Column(
            "missing_modules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflicts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conclusions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "syndrome_points",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "inputs_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fusion_no"),
    )
    op.create_index("ix_fusion_results_session_id", "fusion_results", ["session_id"], unique=False)
    op.create_index(
        "idx_fusion_session", "fusion_results", ["session_id", "is_current"], unique=False
    )
    op.create_index(
        "uq_fusion_current",
        "fusion_results",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("uq_fusion_current", table_name="fusion_results")
    op.drop_index("idx_fusion_session", table_name="fusion_results")
    op.drop_index("ix_fusion_results_session_id", table_name="fusion_results")
    op.drop_table("fusion_results")
    health_level.drop(op.get_bind(), checkfirst=True)