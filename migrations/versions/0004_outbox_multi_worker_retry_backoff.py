"""Outbox multi-worker locking, retry backoff, and wallet reference uniqueness

Revision ID: 0004_outbox_multi_worker_retry_backoff
Revises: 0003_snapshots_timeline_recipients
Create Date: 2026-09-25 19:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision: str = '0004_outbox_multi_worker_retry_backoff'
down_revision: Union[str, Sequence[str], None] = '0003_snapshots_timeline_recipients'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. Add Outbox multi-worker locking and retry columns
    if 'outbox_events' in existing_tables:
        outbox_columns = {col['name'] for col in inspector.get_columns('outbox_events')}
        with op.batch_alter_table('outbox_events', schema=None) as batch_op:
            if 'next_retry_at' not in outbox_columns:
                batch_op.add_column(sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))
            if 'locked_at' not in outbox_columns:
                batch_op.add_column(sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True))
            if 'locked_by' not in outbox_columns:
                batch_op.add_column(sa.Column('locked_by', sa.String(64), nullable=True))

    # 2. Add wallet ledger reference uniqueness constraint
    if 'wallet_transactions' in existing_tables:
        with op.batch_alter_table('wallet_transactions', schema=None) as batch_op:
            try:
                batch_op.create_unique_constraint(
                    'uq_wallet_reference_tx',
                    ['reference_type', 'reference_id', 'tx_type']
                )
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    if 'wallet_transactions' in existing_tables:
        with op.batch_alter_table('wallet_transactions', schema=None) as batch_op:
            try:
                batch_op.drop_constraint('uq_wallet_reference_tx', type_='unique')
            except Exception:
                pass

    if 'outbox_events' in existing_tables:
        with op.batch_alter_table('outbox_events', schema=None) as batch_op:
            batch_op.drop_column('locked_by')
            batch_op.drop_column('locked_at')
            batch_op.drop_column('next_retry_at')
