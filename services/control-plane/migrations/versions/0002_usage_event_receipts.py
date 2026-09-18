"""Chống ghi trùng cho consumer Redis Stream usage (ADR-005).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # stream_id là định danh bất biến của Redis. Không dùng trace_id: một trace có thể có
    # nhiều model call, và unique constraint trên bảng partitioned không đảm bảo toàn cục.
    op.execute(
        """
        CREATE TABLE usage_event_receipts (
          stream_id   text PRIMARY KEY,
          recorded_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON usage_event_receipts TO ben_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_event_receipts")
