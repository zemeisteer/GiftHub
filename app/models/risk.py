from enum import Enum

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class RiskType(str, Enum):
    REFERRAL_VELOCITY = "referral_velocity"
    PROMO_BRUTEFORCE = "promo_bruteforce"
    CHECKOUT_SPAM = "checkout_spam"
    UNUSUAL_AMOUNT = "unusual_amount"
    SELF_REFERRAL = "self_referral"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskAudit(Base):
    """
    Log of risk anomalies, abuse attempts, and fraud flags.
    """
    __tablename__ = "risk_audits"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    risk_type = Column(String(32), nullable=False, index=True)
    severity = Column(String(16), default=RiskSeverity.MEDIUM.value, nullable=False, index=True)
    details = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True, default=dict)
    is_actioned = Column(Boolean, default=False, nullable=False) # e.g. auto-blocked, admin reviewed
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
