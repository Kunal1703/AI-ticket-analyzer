"""tickets.status (ticket lifecycle)

Revision ID: 0010_ticket_status
Revises: 0009_routing_sla
Create Date: 2026-07-09

Adds the ticket lifecycle ``status`` column (M3.6). The ``server_default 'open'``
backfills existing rows so the NOT NULL add is safe on a populated table;
new rows also default to ``'open'``.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_ticket_status"
down_revision: str | None = "0009_routing_sla"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tickets", "status")
