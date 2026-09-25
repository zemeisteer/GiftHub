from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class TicketStatus:
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(
        String(64), default="other", nullable=False
    )  # order, payment, stars, premium, gifts, account, other
    subject = Column(String(128), nullable=False)
    status = Column(String(32), default=TicketStatus.OPEN, index=True, nullable=False)
    assigned_admin_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="support_tickets")
    messages = relationship(
        "TicketMessage", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at"
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(BigInteger, nullable=False)
    sender_type = Column(String(16), nullable=False)  # user, admin
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    ticket = relationship("SupportTicket", back_populates="messages")
