from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String

from app.models.base import Base


class TelegramGift(Base):
    """Real Telegram gift (sendGift) mirrored from the Bot API catalog."""

    __tablename__ = "telegram_gifts"

    id = Column(String(64), primary_key=True)
    emoji = Column(String(16), default="🎁", nullable=False)
    title = Column(String(64), nullable=True)
    star_count = Column(Integer, nullable=False)
    is_limited = Column(Boolean, default=False, nullable=False)
    remaining_count = Column(Integer, nullable=True)
    is_premium = Column(Boolean, default=False, nullable=False)
    available = Column(Boolean, default=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    price_override_uzs = Column(Numeric(18, 2), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)


class GiftSyncState(Base):
    """Single-row (id=1) state of the gift catalog / bot Stars balance sync."""

    __tablename__ = "gift_sync_state"

    id = Column(Integer, primary_key=True, default=1)
    bot_star_balance = Column(Integer, nullable=True)
    balance_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_error = Column(String(255), nullable=True)
