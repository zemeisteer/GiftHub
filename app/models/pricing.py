from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)

from app.models.base import Base, utc_now


class PricingSetting(Base):
    __tablename__ = "pricing_settings"

    id = Column(Integer, primary_key=True)
    stars_cost_ton = Column(Numeric(18, 6), default=Decimal("0.0021"))  # 1 Star cost in TON
    ton_rate_uzs = Column(Numeric(18, 2), default=Decimal("14800.00"))  # 1 TON in UZS
    margin_percent = Column(Numeric(18, 2), default=Decimal("15.00"))  # Margin percentage
    star_unit_price_uzs = Column(Numeric(18, 2), default=Decimal("180.00"))  # Direct 1 Star base cost in UZS
    minimum_margin = Column(Numeric(18, 2), default=Decimal("5.00"))  # Configurable safeguard
    maximum_discount = Column(Numeric(18, 2), default=Decimal("30.00"))  # Safeguard
    minimum_price = Column(Numeric(18, 2), default=Decimal("1000.00"))  # Safeguard
    stars_discounts_json = Column(
        Text, default='[{"min_amount": 500, "discount_pct": 5}, {"min_amount": 1000, "discount_pct": 8}]'
    )
    premium_prices_json = Column(Text, default='{"3": 142000, "6": 210000, "12": 380000}')
    gifts_json = Column(
        Text,
        default='[{"id": "bear", "name": "Teddy Bear", "price_uzs": 64000, "cost_uzs": 50000, "icon": "🧸", "type": "3d"}, {"id": "heart", "name": "Neon Heart", "price_uzs": 85000, "cost_uzs": 68000, "icon": "💖", "type": "3d"}, {"id": "rocket", "name": "Cosmo Rocket", "price_uzs": 120000, "cost_uzs": 95000, "icon": "🚀", "type": "3d"}, {"id": "star", "name": "Cosmic Star", "price_uzs": 60000, "cost_uzs": 45000, "icon": "⭐", "type": "classic"}, {"id": "ring", "name": "Diamond Ring", "price_uzs": 165000, "cost_uzs": 130000, "icon": "💍", "type": "3d"}, {"id": "trophy", "name": "Gold Trophy", "price_uzs": 195000, "cost_uzs": 155000, "icon": "🏆", "type": "vip"}, {"id": "yacht", "name": "Luxury Yacht", "price_uzs": 270000, "cost_uzs": 220000, "icon": "🛥️", "type": "vip"}, {"id": "crown", "name": "Ruby Crown", "price_uzs": 225000, "cost_uzs": 180000, "icon": "👑", "type": "vip"}, {"id": "medal", "name": "Star Medal", "price_uzs": 95000, "cost_uzs": 75000, "icon": "🎖️", "type": "classic"}, {"id": "hat", "name": "Magic Hat", "price_uzs": 78000, "cost_uzs": 60000, "icon": "🎩", "type": "classic"}, {"id": "eagle", "name": "Flying Eagle", "price_uzs": 110000, "cost_uzs": 88000, "icon": "🦅", "type": "3d"}, {"id": "lion", "name": "Golden Lion", "price_uzs": 175000, "cost_uzs": 140000, "icon": "🦁", "type": "vip"}]',
    )
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PriceLock(Base):
    """
    Checkout Price Lock.
    Prevents exchange-rate swings during active checkouts by locking the calculated price.
    """

    __tablename__ = "price_locks"

    id = Column(String(64), primary_key=True)  # UUID / Unique token
    product_type = Column(String(32), nullable=False)
    amount = Column(Integer, nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    total_price = Column(Numeric(18, 2), nullable=False)
    cost_price = Column(Numeric(18, 2), nullable=False)
    ton_rate_snapshot = Column(Numeric(18, 2), nullable=False)
    margin_snapshot = Column(Numeric(18, 2), nullable=False)
    discount_snapshot = Column(Numeric(18, 2), default=Decimal("0.00"))
    user_id = Column(BigInteger, nullable=True, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
