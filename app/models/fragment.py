from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text

from app.models.base import Base, utc_now


class FragmentSetting(Base):
    __tablename__ = "fragment_settings"

    id = Column(Integer, primary_key=True)
    is_auto_buy = Column(Boolean, default=True, nullable=False)
    ton_wallet_address = Column(String(128), default="")
    ton_wallet_mnemonic = Column(Text, default="")
    tonapi_key = Column(String(128), default="")
    network = Column(String(32), default="mainnet")  # mainnet, testnet
    min_ton_balance = Column(Numeric(18, 4), default=Decimal("1.0000"))
    simulation_mode = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
