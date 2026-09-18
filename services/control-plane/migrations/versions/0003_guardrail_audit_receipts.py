"""Idempotence receipts cho consumer audit guardrail.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE guardrail_audit_receipts (
          stream_id   text PRIMARY KEY,
          recorded_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON guardrail_audit_receipts TO ben_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS guardrail_audit_receipts")
