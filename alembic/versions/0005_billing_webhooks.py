"""billing webhooks: processed_webhook_events + organizations.stripe_customer_id

Revision ID: 0005_billing_webhooks
Revises: 0004_usage_events
Create Date: 2026-07-02

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_billing_webhooks"
down_revision: str | None = "0004_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processed_webhook_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_processed_webhook_events_event_id")),
    )

    # Stripe customer linkage on organizations (nullable, unique).
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_organizations_stripe_customer_id"),
        "organizations",
        ["stripe_customer_id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_organizations_stripe_customer_id"), "organizations", type_="unique")
    op.drop_column("organizations", "stripe_customer_id")
    op.drop_table("processed_webhook_events")
