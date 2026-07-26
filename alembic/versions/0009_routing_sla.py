"""routing_rules + sla_policies + tickets.assignee/sla_due_at

Revision ID: 0009_routing_sla
Revises: 0008_webhooks
Create Date: 2026-07-03

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_routing_sla"
down_revision: str | None = "0008_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_routing_rules_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routing_rules")),
    )
    op.create_index(op.f("ix_routing_rules_organization_id"), "routing_rules", ["organization_id"])

    op.create_table(
        "sla_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_sla_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policies")),
    )
    op.create_index(op.f("ix_sla_policies_organization_id"), "sla_policies", ["organization_id"])

    op.add_column("tickets", sa.Column("assignee", sa.String(length=255), nullable=True))
    op.add_column("tickets", sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "sla_due_at")
    op.drop_column("tickets", "assignee")
    op.drop_index(op.f("ix_sla_policies_organization_id"), table_name="sla_policies")
    op.drop_table("sla_policies")
    op.drop_index(op.f("ix_routing_rules_organization_id"), table_name="routing_rules")
    op.drop_table("routing_rules")
