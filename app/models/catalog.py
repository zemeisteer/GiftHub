from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Integer, Numeric, String, Text

from app.models.base import Base, utc_now


class CatalogProduct(Base):
    """
    Database-driven product catalog for Stars bundles, Premium durations, and Gifts.
    Allows enabling/disabling and price updates from Admin Panel without redeploying.
    """

    __tablename__ = "catalog_products"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    category = Column(String(32), nullable=False, index=True)  # stars, premium, gift, custom
    sku = Column(String(64), unique=True, nullable=False, index=True)  # e.g. stars_50, premium_3m
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Integer, default=1, nullable=False)  # e.g. 50 (stars)
    duration_months = Column(Integer, nullable=True)  # e.g. 3, 6, 12 for premium
    base_price_uzs = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    display_order = Column(Integer, default=0, nullable=False)
    badge_text = Column(String(32), nullable=True)  # e.g. "Popular", "-15%"
    metadata_json = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
