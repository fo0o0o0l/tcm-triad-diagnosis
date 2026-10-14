"""create tongue tables

Revision ID: a1b2c3d4e5f6
Revises: 99fe7a027153
Create Date: 2026-10-12 19:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "99fe7a027153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tongue_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "source",
            sa.Enum("upload", "camera", name="image_source"),
            nullable=False,
        ),
        sa.Column("image_ref", sa.String(length=255), nullable=False),
        sa.Column("quality_passed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "quality_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("mask_ref", sa.String(length=255), nullable=True),
        sa.Column("extract_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "extract_status",
            sa.Enum(
                "pending",
                "collecting",
                "extracting",
                "analyzed",
                "failed",
                name="module_status",
            ),
            server_default="pending",
            nullable=False,
        ),
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
    op.create_index("ix_tongue_records_session_id", "tongue_records", ["session_id"], unique=False)
    op.create_index(
        "uq_tongue_session",
        "tongue_records",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "tongue_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_no", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "analyzing", "completed", "failed", name="analysis_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("tongue_summary", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["record_id"], ["tongue_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_no"),
    )
    op.create_index(
        "idx_tongue_analysis_record",
        "tongue_analyses",
        ["record_id", "is_current"],
        unique=False,
    )
    op.create_index(
        "uq_tongue_analysis_current",
        "tongue_analyses",
        ["record_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("uq_tongue_analysis_current", table_name="tongue_analyses")
    op.drop_index("idx_tongue_analysis_record", table_name="tongue_analyses")
    op.drop_table("tongue_analyses")
    op.drop_index("uq_tongue_session", table_name="tongue_records")
    op.drop_index("ix_tongue_records_session_id", table_name="tongue_records")
    op.drop_table("tongue_records")
    # PG 原生枚举不随 drop_table 自动清除，需显式删除以支持 downgrade/upgrade 重放
    postgresql.ENUM(name="analysis_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="module_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="image_source").drop(op.get_bind(), checkfirst=True)