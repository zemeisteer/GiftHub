"""Initial schema and GiftHub production architecture upgrade

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-24 22:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. users
    if 'users' not in existing_tables:
        op.create_table(
            'users',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('first_name', sa.String(length=128), nullable=False, server_default=''),
            sa.Column('last_name', sa.String(length=128), nullable=True, server_default=''),
            sa.Column('username', sa.String(length=64), nullable=True),
            sa.Column('photo_url', sa.String(length=512), nullable=True),
            sa.Column('balance', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('referrer_id', sa.BigInteger(), nullable=True),
            sa.Column('referral_earnings', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('referrals_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('role', sa.String(length=32), nullable=False, server_default='user'),
            sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('users') as batch_op:
            batch_op.create_index('ix_users_id', ['id'])
            batch_op.create_index('ix_users_username', ['username'])
            batch_op.create_index('ix_users_referrer_id', ['referrer_id'])
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('users')}
        with op.batch_alter_table('users') as batch_op:
            if 'updated_at' not in existing_cols:
                batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # 2. pricing_settings
    if 'pricing_settings' not in existing_tables:
        op.create_table(
            'pricing_settings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('stars_cost_ton', sa.Numeric(precision=18, scale=6), server_default='0.0021'),
            sa.Column('ton_rate_uzs', sa.Numeric(precision=18, scale=2), server_default='14800.00'),
            sa.Column('margin_percent', sa.Numeric(precision=18, scale=2), server_default='15.00'),
            sa.Column('star_unit_price_uzs', sa.Numeric(precision=18, scale=2), server_default='180.00'),
            sa.Column('minimum_margin', sa.Numeric(precision=18, scale=2), server_default='5.00'),
            sa.Column('maximum_discount', sa.Numeric(precision=18, scale=2), server_default='30.00'),
            sa.Column('minimum_price', sa.Numeric(precision=18, scale=2), server_default='1000.00'),
            sa.Column('stars_discounts_json', sa.Text(), nullable=True),
            sa.Column('premium_prices_json', sa.Text(), nullable=True),
            sa.Column('gifts_json', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('pricing_settings')}
        with op.batch_alter_table('pricing_settings') as batch_op:
            if 'minimum_margin' not in existing_cols:
                batch_op.add_column(sa.Column('minimum_margin', sa.Numeric(precision=18, scale=2), server_default='5.00'))
            if 'maximum_discount' not in existing_cols:
                batch_op.add_column(sa.Column('maximum_discount', sa.Numeric(precision=18, scale=2), server_default='30.00'))
            if 'minimum_price' not in existing_cols:
                batch_op.add_column(sa.Column('minimum_price', sa.Numeric(precision=18, scale=2), server_default='1000.00'))

    # 3. orders
    if 'orders' not in existing_tables:
        op.create_table(
            'orders',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('order_code', sa.String(length=32), unique=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('product_type', sa.String(length=32), nullable=False),
            sa.Column('item_title', sa.String(length=128), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('unit_price', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('total_price', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('cost_price', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('discount_amount', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('promo_code', sa.String(length=32), nullable=True),
            sa.Column('payment_method', sa.String(length=32), nullable=False, server_default='balance'),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='created'),
            sa.Column('recipient_username', sa.String(length=64), nullable=True),
            sa.Column('price_lock_id', sa.String(length=64), nullable=True),
            sa.Column('fragment_req_id', sa.String(length=64), nullable=True),
            sa.Column('fragment_payload', sa.Text(), nullable=True),
            sa.Column('fragment_tx_hash', sa.String(length=128), nullable=True),
            sa.Column('fulfillment_status', sa.String(length=32), server_default='pending'),
            sa.Column('fulfillment_attempts', sa.Integer(), server_default='0'),
            sa.Column('fulfillment_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('processing_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('orders') as batch_op:
            batch_op.create_index('ix_orders_order_code', ['order_code'], unique=True)
            batch_op.create_index('ix_orders_user_id', ['user_id'])
            batch_op.create_index('ix_orders_status', ['status'])
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('orders')}
        with op.batch_alter_table('orders') as batch_op:
            if 'discount_amount' not in existing_cols:
                batch_op.add_column(sa.Column('discount_amount', sa.Numeric(precision=18, scale=2), server_default='0.00'))
            if 'promo_code' not in existing_cols:
                batch_op.add_column(sa.Column('promo_code', sa.String(length=32), nullable=True))
            if 'payment_method' not in existing_cols:
                batch_op.add_column(sa.Column('payment_method', sa.String(length=32), server_default='balance'))
            if 'price_lock_id' not in existing_cols:
                batch_op.add_column(sa.Column('price_lock_id', sa.String(length=64), nullable=True))
            if 'fulfillment_attempts' not in existing_cols:
                batch_op.add_column(sa.Column('fulfillment_attempts', sa.Integer(), server_default='0'))
            if 'paid_at' not in existing_cols:
                batch_op.add_column(sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
            if 'processing_at' not in existing_cols:
                batch_op.add_column(sa.Column('processing_at', sa.DateTime(timezone=True), nullable=True))
            if 'cancelled_at' not in existing_cols:
                batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
            if 'refunded_at' not in existing_cols:
                batch_op.add_column(sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True))

    # 4. wallet_transactions
    if 'wallet_transactions' not in existing_tables:
        op.create_table(
            'wallet_transactions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('tx_type', sa.String(length=32), nullable=False),
            sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('currency', sa.String(length=8), nullable=False, server_default='UZS'),
            sa.Column('balance_before', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('balance_after', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('reference_type', sa.String(length=64), nullable=True),
            sa.Column('reference_id', sa.String(length=128), nullable=True),
            sa.Column('note', sa.String(length=255), nullable=True),
            sa.Column('meta_info', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table('wallet_transactions') as batch_op:
            batch_op.create_index('ix_wallet_transactions_user_id', ['user_id'])
            batch_op.create_index('ix_wallet_transactions_reference_type', ['reference_type'])
            batch_op.create_index('ix_wallet_transactions_reference_id', ['reference_id'])

    # 5. payment_transactions
    if 'payment_transactions' not in existing_tables:
        op.create_table(
            'payment_transactions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('provider', sa.String(length=32), nullable=False),
            sa.Column('provider_transaction_id', sa.String(length=128), nullable=False),
            sa.Column('idempotency_key', sa.String(length=128), unique=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True),
            sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('currency', sa.String(length=8), nullable=False, server_default='UZS'),
            sa.Column('status', sa.String(length=32), server_default='pending'),
            sa.Column('raw_payload', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint('provider', 'provider_transaction_id', name='uq_provider_tx_id')
        )
        with op.batch_alter_table('payment_transactions') as batch_op:
            batch_op.create_index('ix_payment_transactions_provider', ['provider'])
            batch_op.create_index('ix_payment_transactions_provider_tx_id', ['provider_transaction_id'])
            batch_op.create_index('ix_payment_transactions_idempotency_key', ['idempotency_key'], unique=True)
            batch_op.create_index('ix_payment_transactions_user_id', ['user_id'])
            batch_op.create_index('ix_payment_transactions_order_id', ['order_id'])
            batch_op.create_index('ix_payment_transactions_status', ['status'])

    # 6. price_locks
    if 'price_locks' not in existing_tables:
        op.create_table(
            'price_locks',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('product_type', sa.String(length=32), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False),
            sa.Column('unit_price', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('total_price', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('cost_price', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('ton_rate_snapshot', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('margin_snapshot', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('discount_snapshot', sa.Numeric(precision=18, scale=2), server_default='0.00'),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('price_locks') as batch_op:
            batch_op.create_index('ix_price_locks_expires_at', ['expires_at'])
            batch_op.create_index('ix_price_locks_user_id', ['user_id'])

    # 7. promo_codes & promo_redemptions
    if 'promo_codes' not in existing_tables:
        op.create_table(
            'promo_codes',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('code', sa.String(length=32), unique=True, nullable=False),
            sa.Column('reward_type', sa.String(length=32), nullable=False, server_default='discount_percent'),
            sa.Column('reward_value', sa.Numeric(precision=18, scale=2), nullable=False, server_default='10.00'),
            sa.Column('max_discount', sa.Numeric(precision=18, scale=2), nullable=True),
            sa.Column('min_order_amount', sa.Numeric(precision=18, scale=2), nullable=False, server_default='0.00'),
            sa.Column('max_uses', sa.Integer(), nullable=False, server_default='100'),
            sa.Column('current_uses', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_uses_per_user', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('applicable_products', sa.String(length=128), nullable=False, server_default='all'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('promo_codes') as batch_op:
            batch_op.create_index('ix_promo_codes_code', ['code'], unique=True)
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('promo_codes')}
        with op.batch_alter_table('promo_codes') as batch_op:
            if 'max_discount' not in existing_cols:
                batch_op.add_column(sa.Column('max_discount', sa.Numeric(precision=18, scale=2), nullable=True))
            if 'max_uses_per_user' not in existing_cols:
                batch_op.add_column(sa.Column('max_uses_per_user', sa.Integer(), server_default='1'))
            if 'applicable_products' not in existing_cols:
                batch_op.add_column(sa.Column('applicable_products', sa.String(length=128), server_default='all'))
            if 'starts_at' not in existing_cols:
                batch_op.add_column(sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True))

    if 'promo_redemptions' not in existing_tables:
        op.create_table(
            'promo_redemptions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('promo_code_id', sa.Integer(), sa.ForeignKey('promo_codes.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True),
            sa.Column('benefit_amount', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('promo_redemptions') as batch_op:
            batch_op.create_index('ix_promo_redemptions_promo_code_id', ['promo_code_id'])
            batch_op.create_index('ix_promo_redemptions_user_id', ['user_id'])
            batch_op.create_index('ix_promo_redemptions_order_id', ['order_id'])

    # 8. referral_settings & referral_rewards
    if 'referral_settings' not in existing_tables:
        op.create_table(
            'referral_settings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('bonus_percent', sa.Numeric(precision=18, scale=2), server_default='5.00', nullable=False),
            sa.Column('min_purchase_uzs', sa.Numeric(precision=18, scale=2), server_default='20000.00', nullable=False),
            sa.Column('auto_reward', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column('require_purchase', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column('tier_1_count', sa.Integer(), server_default='5'),
            sa.Column('tier_1_percent', sa.Numeric(precision=18, scale=2), server_default='5.00'),
            sa.Column('tier_2_count', sa.Integer(), server_default='20'),
            sa.Column('tier_2_percent', sa.Numeric(precision=18, scale=2), server_default='7.00'),
            sa.Column('tier_3_count', sa.Integer(), server_default='50'),
            sa.Column('tier_3_percent', sa.Numeric(precision=18, scale=2), server_default='10.00'),
        )
    else:
        existing_cols = {c['name'] for c in inspector.get_columns('referral_settings')}
        with op.batch_alter_table('referral_settings') as batch_op:
            if 'tier_1_count' not in existing_cols:
                batch_op.add_column(sa.Column('tier_1_count', sa.Integer(), server_default='5'))
            if 'tier_1_percent' not in existing_cols:
                batch_op.add_column(sa.Column('tier_1_percent', sa.Numeric(precision=18, scale=2), server_default='5.00'))
            if 'tier_2_count' not in existing_cols:
                batch_op.add_column(sa.Column('tier_2_count', sa.Integer(), server_default='20'))
            if 'tier_2_percent' not in existing_cols:
                batch_op.add_column(sa.Column('tier_2_percent', sa.Numeric(precision=18, scale=2), server_default='7.00'))
            if 'tier_3_count' not in existing_cols:
                batch_op.add_column(sa.Column('tier_3_count', sa.Integer(), server_default='50'))
            if 'tier_3_percent' not in existing_cols:
                batch_op.add_column(sa.Column('tier_3_percent', sa.Numeric(precision=18, scale=2), server_default='10.00'))

    if 'referral_rewards' not in existing_tables:
        op.create_table(
            'referral_rewards',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('referrer_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('referred_user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), unique=True, nullable=False),
            sa.Column('commission_rate', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('commission_amount', sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column('status', sa.String(length=32), server_default='paid', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('referral_rewards') as batch_op:
            batch_op.create_index('ix_referral_rewards_referrer_id', ['referrer_id'])
            batch_op.create_index('ix_referral_rewards_referred_user_id', ['referred_user_id'])
            batch_op.create_index('ix_referral_rewards_order_id', ['order_id'], unique=True)

    # 9. support_tickets & ticket_messages
    if 'support_tickets' not in existing_tables:
        op.create_table(
            'support_tickets',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True),
            sa.Column('category', sa.String(length=64), server_default='other', nullable=False),
            sa.Column('subject', sa.String(length=128), nullable=False),
            sa.Column('status', sa.String(length=32), server_default='OPEN', nullable=False),
            sa.Column('assigned_admin_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('support_tickets') as batch_op:
            batch_op.create_index('ix_support_tickets_user_id', ['user_id'])
            batch_op.create_index('ix_support_tickets_order_id', ['order_id'])
            batch_op.create_index('ix_support_tickets_status', ['status'])

    if 'ticket_messages' not in existing_tables:
        op.create_table(
            'ticket_messages',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('support_tickets.id', ondelete='CASCADE'), nullable=False),
            sa.Column('sender_id', sa.BigInteger(), nullable=False),
            sa.Column('sender_type', sa.String(length=16), nullable=False),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('ticket_messages') as batch_op:
            batch_op.create_index('ix_ticket_messages_ticket_id', ['ticket_id'])

    # 10. in_app_notifications
    if 'in_app_notifications' not in existing_tables:
        op.create_table(
            'in_app_notifications',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('type', sa.String(length=32), nullable=False),
            sa.Column('title', sa.String(length=128), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('related_entity', sa.String(length=64), nullable=True),
            sa.Column('is_read', sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table('in_app_notifications') as batch_op:
            batch_op.create_index('ix_in_app_notifications_user_id', ['user_id'])

    # 11. admin_audit_logs enhancement
    if 'admin_audit_logs' in existing_tables:
        existing_cols = {c['name'] for c in inspector.get_columns('admin_audit_logs')}
        with op.batch_alter_table('admin_audit_logs') as batch_op:
            if 'entity_type' not in existing_cols:
                batch_op.add_column(sa.Column('entity_type', sa.String(length=64), nullable=True))
            if 'entity_id' not in existing_cols:
                batch_op.add_column(sa.Column('entity_id', sa.String(length=64), nullable=True))
            if 'old_value' not in existing_cols:
                batch_op.add_column(sa.Column('old_value', sa.Text(), nullable=True))
            if 'new_value' not in existing_cols:
                batch_op.add_column(sa.Column('new_value', sa.Text(), nullable=True))
            if 'reason' not in existing_cols:
                batch_op.add_column(sa.Column('reason', sa.String(length=255), nullable=True))
            if 'ip_address' not in existing_cols:
                batch_op.add_column(sa.Column('ip_address', sa.String(length=64), nullable=True))
            if 'user_agent' not in existing_cols:
                batch_op.add_column(sa.Column('user_agent', sa.String(length=255), nullable=True))
    else:
        op.create_table(
            'admin_audit_logs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('admin_id', sa.BigInteger(), nullable=False),
            sa.Column('admin_username', sa.String(length=64), nullable=True),
            sa.Column('action', sa.String(length=255), nullable=False),
            sa.Column('entity_type', sa.String(length=64), nullable=True),
            sa.Column('entity_id', sa.String(length=64), nullable=True),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('reason', sa.String(length=255), nullable=True),
            sa.Column('ip_address', sa.String(length=64), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table('admin_audit_logs') as batch_op:
            batch_op.create_index('ix_admin_audit_logs_admin_id', ['admin_id'])
            batch_op.create_index('ix_admin_audit_logs_action', ['action'])


def downgrade() -> None:
    pass
