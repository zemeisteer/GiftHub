"""Order snapshots, timeline history, and saved recipients

Revision ID: 0003_snapshots_timeline_recipients
Revises: 0002_reliability_upgrade
Create Date: 2026-09-25 14:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = '0003_snapshots_timeline_recipients'
down_revision: Union[str, Sequence[str], None] = '0002_reliability_upgrade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. Add financial snapshot columns to orders if not present
    order_columns = {col['name'] for col in inspector.get_columns('orders')}
    with op.batch_alter_table('orders', schema=None) as batch_op:
        if 'margin' not in order_columns:
            batch_op.add_column(sa.Column('margin', sa.Numeric(18, 2), nullable=False, server_default='0.00'))
        if 'exchange_rate' not in order_columns:
            batch_op.add_column(sa.Column('exchange_rate', sa.Numeric(18, 4), nullable=False, server_default='1.0000'))
        if 'currency' not in order_columns:
            batch_op.add_column(sa.Column('currency', sa.String(8), nullable=False, server_default='UZS'))

    # 2. order_status_history
    if 'order_status_history' not in existing_tables:
        op.create_table(
            'order_status_history',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('order_code', sa.String(length=32), nullable=False, index=True),
            sa.Column('from_status', sa.String(length=32), nullable=True),
            sa.Column('to_status', sa.String(length=32), nullable=False),
            sa.Column('actor', sa.String(length=32), nullable=False, server_default='SYSTEM'),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )

    # 3. saved_recipients
    if 'saved_recipients' not in existing_tables:
        op.create_table(
            'saved_recipients',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('recipient_username', sa.String(length=64), nullable=False),
            sa.Column('label', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('user_id', 'recipient_username', name='uq_user_recipient'),
        )


def downgrade() -> None:
    op.drop_table('saved_recipients')
    op.drop_table('order_status_history')
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('currency')
        batch_op.drop_column('exchange_rate')
        batch_op.drop_column('margin')
