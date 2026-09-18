from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True) # Telegram User ID
    first_name = Column(String(128), nullable=False, default="")
    last_name = Column(String(128), nullable=True, default="")
    username = Column(String(64), nullable=True, index=True)
    photo_url = Column(String(512), nullable=True)
    balance = Column(Float, default=0.0)
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_earnings = Column(Float, default=0.0)
    referrals_count = Column(Integer, default=0)
    role = Column(String(32), default="user") # super_admin, price_admin, support_admin, marketing_admin, user
    is_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class PricingSetting(Base):
    __tablename__ = "pricing_settings"

    id = Column(Integer, primary_key=True)
    stars_cost_ton = Column(Float, default=0.0021) # 1 Stars cost in TON
    ton_rate_uzs = Column(Float, default=14800.0)  # 1 TON in UZS
    margin_percent = Column(Float, default=15.0)    # Margin percentage
    star_unit_price_uzs = Column(Float, default=180.0) # Direct 1 Star base cost in UZS
    stars_discounts_json = Column(Text, default='[{"min_amount": 500, "discount_pct": 5}, {"min_amount": 1000, "discount_pct": 8}]')
    premium_prices_json = Column(Text, default='{"3": 142000, "6": 210000, "12": 380000}')
    gifts_json = Column(Text, default='[{"id": "bear", "name": "Teddy Bear", "price_uzs": 64000, "cost_uzs": 50000, "icon": "🧸", "type": "3d"}, {"id": "heart", "name": "Neon Heart", "price_uzs": 85000, "cost_uzs": 68000, "icon": "💖", "type": "3d"}, {"id": "rocket", "name": "Cosmo Rocket", "price_uzs": 120000, "cost_uzs": 95000, "icon": "🚀", "type": "3d"}, {"id": "star", "name": "Cosmic Star", "price_uzs": 60000, "cost_uzs": 45000, "icon": "⭐", "type": "classic"}, {"id": "ring", "name": "Diamond Ring", "price_uzs": 165000, "cost_uzs": 130000, "icon": "💍", "type": "3d"}, {"id": "trophy", "name": "Gold Trophy", "price_uzs": 195000, "cost_uzs": 155000, "icon": "🏆", "type": "vip"}, {"id": "yacht", "name": "Luxury Yacht", "price_uzs": 270000, "cost_uzs": 220000, "icon": "🛥️", "type": "vip"}, {"id": "crown", "name": "Ruby Crown", "price_uzs": 225000, "cost_uzs": 180000, "icon": "👑", "type": "vip"}, {"id": "medal", "name": "Star Medal", "price_uzs": 95000, "cost_uzs": 75000, "icon": "🎖️", "type": "classic"}, {"id": "hat", "name": "Magic Hat", "price_uzs": 78000, "cost_uzs": 60000, "icon": "🎩", "type": "classic"}, {"id": "eagle", "name": "Flying Eagle", "price_uzs": 110000, "cost_uzs": 88000, "icon": "🦅", "type": "3d"}, {"id": "lion", "name": "Golden Lion", "price_uzs": 175000, "cost_uzs": 140000, "icon": "🦁", "type": "vip"}]')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_code = Column(String(32), unique=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    product_type = Column(String(32), nullable=False) # stars, premium, gift
    item_title = Column(String(128), nullable=False)
    amount = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)
    total_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    status = Column(String(32), default="pending", index=True) # pending, done, cancel
    recipient_username = Column(String(64), nullable=True)
    fragment_req_id = Column(String(64), nullable=True)
    fragment_payload = Column(Text, nullable=True)
    fragment_tx_hash = Column(String(128), nullable=True)
    fulfillment_status = Column(String(32), default="pending") # pending, processing, fulfilled, failed
    fulfillment_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="orders")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, default=0.0)
    tx_type = Column(String(32), nullable=False) # topup, purchase, refund, referral_bonus
    method = Column(String(32), default="balance") # click, payme, autopaycard, balance, admin
    status = Column(String(32), default="success") # pending, success, failed
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")


class ChannelRequirement(Base):
    __tablename__ = "channel_requirements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    username_or_link = Column(String(255), nullable=False)
    title = Column(String(128), nullable=False)
    req_type = Column(String(32), default="ordinary") # ordinary, join_request, external
    is_active = Column(Boolean, default=True)
    is_detected = Column(Boolean, default=False) # True if auto-detected via my_chat_member but not yet approved
class UserJoinRequest(Base):
    __tablename__ = "user_join_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(BigInteger, nullable=False, index=True)
    admin_username = Column(String(64), nullable=True)
    action = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReferralSetting(Base):
    __tablename__ = "referral_settings"

    id = Column(Integer, primary_key=True)
    bonus_percent = Column(Float, default=5.0)
    min_purchase_uzs = Column(Float, default=20000.0)
    auto_reward = Column(Boolean, default=True)
    require_purchase = Column(Boolean, default=True)


class PaymentSetting(Base):
    __tablename__ = "payment_settings"

    id = Column(Integer, primary_key=True)
    click_active = Column(Boolean, default=True)
    payme_active = Column(Boolean, default=True)
    card_active = Column(Boolean, default=True)
    card_number = Column(String(32), default="8600 1234 5678 9012")
    card_holder = Column(String(128), default="ANVAR S.")
    bank_name = Column(String(64), default="TBC Bank")
    autopaycard_active = Column(Boolean, default=False)
    autopaycard_api_key = Column(String(255), default="")
    autopaycard_last4 = Column(String(8), default="6412")
    autopaycard_email = Column(String(128), default="payments.stellar@gmail.com")
    autopaycard_webhook_url = Column(String(255), default="https://stellar-bot.uz/webhook/autopaycard")


class PaymentCard(Base):
    __tablename__ = "payment_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_number = Column(String(32), nullable=False)
    card_holder = Column(String(128), nullable=False)
    bank_name = Column(String(64), nullable=False)
    card_type = Column(String(32), default="UZCARD")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FragmentSetting(Base):
    __tablename__ = "fragment_settings"

    id = Column(Integer, primary_key=True)
    is_auto_buy = Column(Boolean, default=True) # Avtomatik xarid yoqilgan/o'chirilgan
    ton_wallet_address = Column(String(128), default="") # Botning TON hamyon manzili
    ton_wallet_mnemonic = Column(Text, default="") # 24 ta maxfiy seed so'zlar
    tonapi_key = Column(String(128), default="") # TonAPI yoki Toncenter API kaliti
    network = Column(String(32), default="mainnet") # mainnet, testnet
    min_ton_balance = Column(Float, default=1.0) # Minimal TON qoldig'i ogohlantirish uchun
    simulation_mode = Column(Boolean, default=False) # Haqiqiy TON sarflanmaydigan test rejimi
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BroadcastDraft(Base):
    __tablename__ = "broadcast_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String(32), default="write") # write, forward, postbot
    text = Column(Text, nullable=True)
    photo = Column(String(255), nullable=True)
    button_text = Column(String(64), nullable=True)
    button_url = Column(String(255), nullable=True)
    forward_chat_id = Column(BigInteger, nullable=True)
    forward_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ClickTransaction(Base):
    __tablename__ = "click_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    click_trans_id = Column(BigInteger, unique=True, index=True, nullable=False)
    service_id = Column(Integer, nullable=False)
    merchant_trans_id = Column(String(64), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    action = Column(Integer, nullable=False) # 0: prepare, 1: complete
    error = Column(Integer, default=0)
    error_note = Column(String(255), default="Success")
    sign_time = Column(String(32), nullable=True)
    sign_string = Column(String(255), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), default="prepared") # prepared, completed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymeTransaction(Base):
    __tablename__ = "payme_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paycom_id = Column(String(64), unique=True, index=True, nullable=False)
    paycom_time = Column(BigInteger, nullable=False)
    create_time = Column(BigInteger, default=lambda: int(datetime.utcnow().timestamp() * 1000))
    perform_time = Column(BigInteger, default=0)
    cancel_time = Column(BigInteger, default=0)
    amount = Column(BigInteger, nullable=False) # tiyinda (1 UZS = 100 tiyin)
    state = Column(Integer, default=1) # 1: created, 2: performed, -1: cancelled created, -2: cancelled performed
    reason = Column(Integer, nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    reward_type = Column(String(32), default="discount_percent") # discount_percent, balance_bonus
    reward_value = Column(Float, default=10.0) # 10% yoki 10 000 UZS
    max_uses = Column(Integer, default=100)
    current_uses = Column(Integer, default=0)
    min_order_amount = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    usages = relationship("PromoCodeUsage", back_populates="promo_code", cascade="all, delete-orphan")


class PromoCodeUsage(Base):
    __tablename__ = "promo_code_usages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    benefit_amount = Column(Float, default=0.0)
    used_at = Column(DateTime, default=datetime.utcnow)

    promo_code = relationship("PromoCode", back_populates="usages")


class CustomService(Base):
    __tablename__ = "custom_services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    category = Column(String(64), default="Xizmatlar")
    price_uzs = Column(Float, nullable=False, default=0.0)
    cost_uzs = Column(Float, nullable=False, default=0.0)
    icon = Column(String(16), default="⚡")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


