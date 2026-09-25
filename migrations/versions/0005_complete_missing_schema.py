"""Complete missing schema tables and indexes

Revision ID: 0005_complete_missing_schema
Revises: 0004_outbox_multi_worker_retry_backoff
Create Date: 2026-09-25 20:30:00.000000

"""

from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "0005_complete_missing_schema"
down_revision: Union[str, Sequence[str], None] = "0004_outbox_multi_worker_retry_backoff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. broadcast_drafts
    if "broadcast_drafts" not in existing_tables:
        op.create_table(
            "broadcast_drafts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("mode", sa.String(32), default="write", nullable=False),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("photo", sa.String(255), nullable=True),
            sa.Column("button_text", sa.String(64), nullable=True),
            sa.Column("button_url", sa.String(255), nullable=True),
            sa.Column("forward_chat_id", sa.BigInteger(), nullable=True),
            sa.Column("forward_message_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 2. channel_requirements
    if "channel_requirements" not in existing_tables:
        op.create_table(
            "channel_requirements",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
            sa.Column("username_or_link", sa.String(255), nullable=False),
            sa.Column("title", sa.String(128), nullable=False),
            sa.Column("req_type", sa.String(32), default="ordinary", nullable=False),
            sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
            sa.Column("is_detected", sa.Boolean(), default=False, nullable=False),
        )
        op.create_index("ix_channel_requirements_chat_id", "channel_requirements", ["chat_id"])

    # 3. user_join_requests
    if "user_join_requests" not in existing_tables:
        op.create_table(
            "user_join_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_user_join_requests_user_id", "user_join_requests", ["user_id"])
        op.create_index("ix_user_join_requests_chat_id", "user_join_requests", ["chat_id"])

    # 4. custom_services
    if "custom_services" not in existing_tables:
        op.create_table(
            "custom_services",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("category", sa.String(64), default="Xizmatlar", nullable=False),
            sa.Column("price_uzs", sa.Numeric(18, 2), default=Decimal("0.00"), nullable=False),
            sa.Column("cost_uzs", sa.Numeric(18, 2), default=Decimal("0.00"), nullable=False),
            sa.Column("icon", sa.String(16), default="⚡", nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 5. fragment_settings
    if "fragment_settings" not in existing_tables:
        op.create_table(
            "fragment_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("is_auto_buy", sa.Boolean(), default=True, nullable=False),
            sa.Column("ton_wallet_address", sa.String(128), default=""),
            sa.Column("ton_wallet_mnemonic", sa.Text(), default=""),
            sa.Column("tonapi_key", sa.String(128), default=""),
            sa.Column("network", sa.String(32), default="mainnet"),
            sa.Column("min_ton_balance", sa.Numeric(18, 4), default=Decimal("1.0000")),
            sa.Column("simulation_mode", sa.Boolean(), default=False, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 6. payment_cards
    if "payment_cards" not in existing_tables:
        op.create_table(
            "payment_cards",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("card_number", sa.String(32), nullable=False),
            sa.Column("card_holder", sa.String(128), nullable=False),
            sa.Column("bank_name", sa.String(64), nullable=False),
            sa.Column("card_type", sa.String(32), default="UZCARD"),
            sa.Column("is_active", sa.Boolean(), default=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 7. payment_settings
    if "payment_settings" not in existing_tables:
        op.create_table(
            "payment_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("click_active", sa.Boolean(), default=True),
            sa.Column("payme_active", sa.Boolean(), default=True),
            sa.Column("card_active", sa.Boolean(), default=True),
            sa.Column("card_number", sa.String(32), default="8600 1234 5678 9012"),
            sa.Column("card_holder", sa.String(128), default="ANVAR S."),
            sa.Column("bank_name", sa.String(64), default="TBC Bank"),
            sa.Column("autopaycard_active", sa.Boolean(), default=False),
            sa.Column("autopaycard_api_key", sa.String(255), default=""),
            sa.Column("autopaycard_last4", sa.String(8), default="6412"),
            sa.Column("autopaycard_email", sa.String(128), default="payments.gifthub@gmail.com"),
            sa.Column("autopaycard_webhook_url", sa.String(255), default="https://gifthub.uz/webhook/autopaycard"),
        )

    # 8. click_transactions
    if "click_transactions" not in existing_tables:
        op.create_table(
            "click_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("click_trans_id", sa.BigInteger(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("merchant_trans_id", sa.String(64), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("action", sa.Integer(), nullable=False),
            sa.Column("error", sa.Integer(), default=0),
            sa.Column("error_note", sa.String(255), default="Success"),
            sa.Column("sign_time", sa.String(32), nullable=True),
            sa.Column("sign_string", sa.String(255), nullable=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(32), default="prepared"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_click_transactions_click_trans_id", "click_transactions", ["click_trans_id"], unique=True)
        op.create_index("ix_click_transactions_merchant_trans_id", "click_transactions", ["merchant_trans_id"])
        op.create_index("ix_click_transactions_user_id", "click_transactions", ["user_id"])

    # 9. payme_transactions
    if "payme_transactions" not in existing_tables:
        op.create_table(
            "payme_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("paycom_id", sa.String(64), nullable=False),
            sa.Column("paycom_time", sa.BigInteger(), nullable=False),
            sa.Column("create_time", sa.BigInteger(), default=0, nullable=False),
            sa.Column("perform_time", sa.BigInteger(), default=0),
            sa.Column("cancel_time", sa.BigInteger(), default=0),
            sa.Column("amount", sa.BigInteger(), nullable=False),
            sa.Column("state", sa.Integer(), default=1),
            sa.Column("reason", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_payme_transactions_paycom_id", "payme_transactions", ["paycom_id"], unique=True)
        op.create_index("ix_payme_transactions_user_id", "payme_transactions", ["user_id"])

    # 10. promo_code_usages
    if "promo_code_usages" not in existing_tables:
        op.create_table(
            "promo_code_usages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "promo_code_id", sa.Integer(), sa.ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("benefit_amount", sa.Numeric(18, 2), default=Decimal("0.00")),
            sa.Column("used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_promo_code_usages_promo_code_id", "promo_code_usages", ["promo_code_id"])
        op.create_index("ix_promo_code_usages_user_id", "promo_code_usages", ["user_id"])

    # 11. transactions
    if "transactions" not in existing_tables:
        op.create_table(
            "transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), default=Decimal("0.00"), nullable=False),
            sa.Column("tx_type", sa.String(32), nullable=False),
            sa.Column("method", sa.String(32), default="balance"),
            sa.Column("status", sa.String(32), default="success"),
            sa.Column("note", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_transactions_user_id", "transactions", ["user_id"])

    # 12. Helper indexes
    if "outbox_events" in existing_tables:
        outbox_indexes = {ix["name"] for ix in inspector.get_indexes("outbox_events")}
        if "ix_outbox_events_next_retry_at" not in outbox_indexes:
            try:
                op.create_index("ix_outbox_events_next_retry_at", "outbox_events", ["next_retry_at"])
            except Exception:
                pass

    if "admin_audit_logs" in existing_tables:
        audit_indexes = {ix["name"] for ix in inspector.get_indexes("admin_audit_logs")}
        if "ix_admin_audit_logs_entity_id" not in audit_indexes:
            try:
                op.create_index("ix_admin_audit_logs_entity_id", "admin_audit_logs", ["entity_id"])
            except Exception:
                pass
        if "ix_admin_audit_logs_entity_type" not in audit_indexes:
            try:
                op.create_index("ix_admin_audit_logs_entity_type", "admin_audit_logs", ["entity_type"])
            except Exception:
                pass

    # 13. Check constraints for financial invariants
    if "wallet_transactions" in existing_tables:
        with op.batch_alter_table("wallet_transactions", schema=None) as batch_op:
            try:
                batch_op.create_check_constraint("chk_wallet_amount_non_zero", "amount != 0")
            except Exception:
                pass
            try:
                batch_op.create_check_constraint("chk_wallet_balance_before_non_neg", "balance_before >= 0")
            except Exception:
                pass
            try:
                batch_op.create_check_constraint("chk_wallet_balance_after_non_neg", "balance_after >= 0")
            except Exception:
                pass

    if "users" in existing_tables:
        with op.batch_alter_table("users", schema=None) as batch_op:
            try:
                batch_op.create_check_constraint("chk_users_balance_non_neg", "balance >= 0")
            except Exception:
                pass
            try:
                batch_op.create_check_constraint("chk_users_ref_earnings_non_neg", "referral_earnings >= 0")
            except Exception:
                pass


def downgrade() -> None:
    tables = [
        "transactions",
        "promo_code_usages",
        "payme_transactions",
        "click_transactions",
        "payment_settings",
        "payment_cards",
        "fragment_settings",
        "custom_services",
        "user_join_requests",
        "channel_requirements",
        "broadcast_drafts",
    ]
    for table in tables:
        try:
            op.drop_table(table)
        except Exception:
            pass
