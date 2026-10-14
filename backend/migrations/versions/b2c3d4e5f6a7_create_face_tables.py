"""create face tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 复用舌诊迁移已创建的 PG 原生枚举，禁止重复 CREATE TYPE（create_type=False）
image_source = postgresql.ENUM("upload", "camera", name="image_source", create_type=False)
module_status = postgresql.ENUM(
    "pending",
    "collecting",
    "extracting",
    "analyzed",
    "failed",
    name="module_status",
    create_type=False,
)
analysis_status = postgresql.ENUM(
    "pending", "analyzing", "completed", "failed", name="analysis_status", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "face_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("source", image_source, nullable=False),
        sa.Column("image_ref", sa.String(length=255), nullable=False),
        sa.Column("quality_passed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "quality_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("face_count", sa.Integer(), nullable=True),
        sa.Column(
            "regions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("detect_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("detect_status", module_status, server_default="pending", nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("overall_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_no"),
    )
    op.create_index("ix_face_records_session_id", "face_records", ["session_id"], unique=False)
    op.create_index(
        "uq_face_session",
        "face_records",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "face_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_no", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column("status", analysis_status, server_default="pending", nullable=False),
        sa.Column("face_summary", sa.Text(), nullable=True),
        sa.Column("main_syndrome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "secondary_syndromes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "treatment_principles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "recommendations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(["record_id"], ["face_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_no"),
    )
    op.create_index(
        "idx_face_analysis_record",
        "face_analyses",
        ["record_id", "is_current"],
        unique=False,
    )
    op.create_index(
        "uq_face_analysis_current",
        "face_analyses",
        ["record_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("uq_face_analysis_current", table_name="face_analyses")
    op.drop_index("idx_face_analysis_record", table_name="face_analyses")
    op.drop_table("face_analyses")
    op.drop_index("uq_face_session", table_name="face_records")
    op.drop_index("ix_face_records_session_id", table_name="face_records")
    op.drop_table("face_records")
    # image_source / module_status / analysis_status 为舌诊迁移共享枚举，此处不删除