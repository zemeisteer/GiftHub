from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text

from app.models.base import Base, utc_now


class AdminAuditLog(Base):
    """
    Immutable Admin Audit Log.
    Records all sensitive administrative actions for compliance and traceability.
    """

    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(BigInteger, nullable=False, index=True)
    admin_username = Column(String(64), nullable=True)
    action = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(64), nullable=True, index=True)  # order, user, pricing, payment, promo, admin
    entity_id = Column(String(64), nullable=True, index=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(String(255), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
