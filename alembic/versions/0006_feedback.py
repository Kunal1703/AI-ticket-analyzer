"""feedback: human feedback on ticket analyses (training signal)

Revision ID: 0006_feedback
Revises: 0005_billing_webhooks
Create Date: 2026-07-02

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_feedback"
down_revision: str | None = "0005_billing_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("corrected_category", sa.String(length=64), nullable=True),
        sa.Column("corrected_priority", sa.String(length=32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_feedback_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk_feedback_ticket_id_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_feedback_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index(op.f("ix_feedback_organization_id"), "feedback", ["organization_id"])
    op.create_index(op.f("ix_feedback_ticket_id"), "feedback", ["ticket_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_feedback_ticket_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_organization_id"), table_name="feedback")
    op.drop_table("feedback")
