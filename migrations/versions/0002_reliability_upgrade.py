"""Reliability upgrade: outbox, dlq, provider health, feature flags, catalog, reconciliation, risk and constraints

Revision ID: 0002_reliability_upgrade
Revises: 0001_initial_schema
Create Date: 2026-09-25 13:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = '0002_reliability_upgrade'
down_revision: Union[str, Sequence[str], None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. outbox_events
    if 'outbox_events' not in existing_tables:
        op.create_table(
            'outbox_events',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('event_type', sa.String(length=64), nullable=False, index=True),
            sa.Column('aggregate_type', sa.String(length=32), nullable=False, index=True),
            sa.Column('aggregate_id', sa.String(length=64), nullable=False, index=True),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending', index=True),
            sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_retries', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('correlation_id', sa.String(length=64), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        )

    # 2. failed_jobs (Dead Letter Queue)
    if 'failed_jobs' not in existing_tables:
        op.create_table(
            'failed_jobs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('job_type', sa.String(length=64), nullable=False, index=True),
            sa.Column('order_id', sa.BigInteger(), nullable=True, index=True),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('error_message', sa.Text(), nullable=False),
            sa.Column('traceback', sa.Text(), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='exhausted', index=True),
            sa.Column('resolution_notes', sa.Text(), nullable=True),
            sa.Column('resolved_by', sa.BigInteger(), nullable=True),
            sa.Column('correlation_id', sa.String(length=64), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        )

    # 3. provider_health
    if 'provider_health' not in existing_tables:
        op.create_table(
            'provider_health',
            sa.Column('provider_name', sa.String(length=32), primary_key=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='healthy'),
            sa.Column('circuit_state', sa.String(length=20), nullable=False, server_default='closed'),
            sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('success_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('disabled_reason', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )

    # 4. feature_flags
    if 'feature_flags' not in existing_tables:
        op.create_table(
            'feature_flags',
            sa.Column('name', sa.String(length=64), primary_key=True),
            sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )

    # 5. catalog_products
    if 'catalog_products' not in existing_tables:
        op.create_table(
            'catalog_products',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('category', sa.String(length=32), nullable=False, index=True),
            sa.Column('sku', sa.String(length=64), unique=True, nullable=False, index=True),
            sa.Column('title', sa.String(length=128), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('duration_months', sa.Integer(), nullable=True),
            sa.Column('base_price_uzs', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('badge_text', sa.String(length=32), nullable=True),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )

    # 6. reconciliation_reports & reconciliation_discrepancies
    if 'reconciliation_reports' not in existing_tables:
        op.create_table(
            'reconciliation_reports',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('total_payments_checked', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_orders_checked', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_wallet_tx_checked', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('discrepancies_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='clean'),
            sa.Column('summary_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        )

    if 'reconciliation_discrepancies' not in existing_tables:
        op.create_table(
            'reconciliation_discrepancies',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('report_id', sa.Integer(), sa.ForeignKey('reconciliation_reports.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('discrepancy_type', sa.String(length=64), nullable=False, index=True),
            sa.Column('order_id', sa.BigInteger(), nullable=True, index=True),
            sa.Column('payment_id', sa.BigInteger(), nullable=True, index=True),
            sa.Column('expected_value', sa.String(length=128), nullable=True),
            sa.Column('actual_value', sa.String(length=128), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
            sa.Column('resolved_by', sa.BigInteger(), nullable=True),
            sa.Column('resolution_notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        )

    # 7. risk_audits
    if 'risk_audits' not in existing_tables:
        op.create_table(
            'risk_audits',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('risk_type', sa.String(length=32), nullable=False, index=True),
            sa.Column('severity', sa.String(length=16), nullable=False, server_default='medium', index=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('is_actioned', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        )

    # 8. checkout_idempotency
    if 'checkout_idempotency' not in existing_tables:
        op.create_table(
            'checkout_idempotency',
            sa.Column('idempotency_key', sa.String(length=128), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True),
            sa.Column('request_hash', sa.String(length=64), nullable=False),
            sa.Column('response_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        )

    # Check and add columns on existing tables
    if 'orders' in existing_tables:
        orders_cols = {c['name'] for c in inspector.get_columns('orders')}
        if 'correlation_id' not in orders_cols:
            op.add_column('orders', sa.Column('correlation_id', sa.String(length=64), nullable=True))
            op.create_index('ix_orders_correlation_id', 'orders', ['correlation_id'])

    if 'payment_transactions' in existing_tables:
        pt_cols = {c['name'] for c in inspector.get_columns('payment_transactions')}
        if 'correlation_id' not in pt_cols:
            op.add_column('payment_transactions', sa.Column('correlation_id', sa.String(length=64), nullable=True))
            op.create_index('ix_payment_transactions_correlation_id', 'payment_transactions', ['correlation_id'])

    if 'users' in existing_tables:
        users_cols = {c['name'] for c in inspector.get_columns('users')}
        if 'is_flagged_for_abuse' not in users_cols:
            op.add_column('users', sa.Column('is_flagged_for_abuse', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    pass
