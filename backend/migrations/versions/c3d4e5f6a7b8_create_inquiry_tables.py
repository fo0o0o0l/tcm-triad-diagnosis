"""create inquiry tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 复用舌诊迁移已创建的 PG 原生枚举，禁止重复 CREATE TYPE（create_type=False）
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
        "inquiry_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column(
            "patient_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", module_status, server_default="pending", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_inquiry_records_session_id", "inquiry_records", ["session_id"], unique=False
    )
    op.create_index(
        "uq_inquiry_session",
        "inquiry_records",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "inquiry_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_no", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column("status", analysis_status, server_default="pending", nullable=False),
        sa.Column("symptoms_summary", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["record_id"], ["inquiry_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_no"),
    )
    op.create_index(
        "idx_inquiry_analysis_record",
        "inquiry_analyses",
        ["record_id", "is_current"],
        unique=False,
    )
    op.create_index(
        "uq_inquiry_analysis_current",
        "inquiry_analyses",
        ["record_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "inquiry_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )

    op.create_table(
        "inquiry_drafts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
    )
    op.create_index("ix_inquiry_drafts_session_id", "inquiry_drafts", ["session_id"], unique=False)
    op.create_index("uq_inquiry_draft_session", "inquiry_drafts", ["session_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_inquiry_draft_session", table_name="inquiry_drafts")
    op.drop_index("ix_inquiry_drafts_session_id", table_name="inquiry_drafts")
    op.drop_table("inquiry_drafts")
    op.drop_table("inquiry_templates")
    op.drop_index("uq_inquiry_analysis_current", table_name="inquiry_analyses")
    op.drop_index("idx_inquiry_analysis_record", table_name="inquiry_analyses")
    op.drop_table("inquiry_analyses")
    op.drop_index("uq_inquiry_session", table_name="inquiry_records")
    op.drop_index("ix_inquiry_records_session_id", table_name="inquiry_records")
    op.drop_table("inquiry_records")
    # module_status / analysis_status 为舌诊迁移共享枚举，此处不删除