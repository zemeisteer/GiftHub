"""Telegram gifts: catalog tables, orders.recipient_user_id, legacy gift quarantine

Revision ID: 0006_telegram_gifts
Revises: 0005_complete_missing_schema
Create Date: 2026-11-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "0006_telegram_gifts"
down_revision: Union[str, Sequence[str], None] = "0005_complete_missing_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Old Fragment flow left wallet-paid gift orders (status 'paid'/'processing') in any of these fulfillment states,
# including 'waiting_payment' and 'failed' (not refunded). Module-level so tests can run it against SQLite.
QUARANTINE_LEGACY_GIFTS_SQL = (
    "UPDATE orders SET fulfillment_status='manual_review', "
    "fulfillment_error='Eski katalog: qo''lda ko''rib chiqing' "
    "WHERE product_type='gift' AND status IN ('paid','processing') "
    "AND fulfillment_status IN ('pending','processing','retry_scheduled','waiting_payment','failed') "
    "AND recipient_user_id IS NULL"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    if "telegram_gifts" not in existing_tables:
        op.create_table(
            "telegram_gifts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("emoji", sa.String(16), nullable=False, server_default="🎁"),
            sa.Column("title", sa.String(64), nullable=True),
            sa.Column("star_count", sa.Integer(), nullable=False),
            sa.Column("is_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("remaining_count", sa.Integer(), nullable=True),
            sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("price_override_uzs", sa.Numeric(18, 2), nullable=True),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "gift_sync_state" not in existing_tables:
        op.create_table(
            "gift_sync_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("bot_star_balance", sa.Integer(), nullable=True),
            sa.Column("balance_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_error", sa.String(255), nullable=True),
        )

    if "orders" in existing_tables:
        order_columns = {c["name"] for c in inspector.get_columns("orders")}
        if "recipient_user_id" not in order_columns:
            op.add_column("orders", sa.Column("recipient_user_id", sa.BigInteger(), nullable=True))

        # Quarantine in-flight gift orders created against the old (non-Telegram) catalog.
        op.execute(sa.text(QUARANTINE_LEGACY_GIFTS_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    if "orders" in existing_tables:
        order_columns = {c["name"] for c in inspector.get_columns("orders")}
        if "recipient_user_id" in order_columns:
            with op.batch_alter_table("orders", schema=None) as batch_op:
                batch_op.drop_column("recipient_user_id")

    for table in ("gift_sync_state", "telegram_gifts"):
        if table in existing_tables:
            op.drop_table(table)
