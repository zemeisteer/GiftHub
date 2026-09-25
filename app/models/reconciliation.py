from enum import Enum

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utc_now


class DiscrepancyType(str, Enum):
    PAID_PAYMENT_UNPAID_ORDER = "paid_payment_unpaid_order"
    PAID_ORDER_MISSING_WALLET_TX = "paid_order_missing_wallet_tx"
    PAID_ORDER_MISSING_FULFILLMENT = "paid_order_missing_fulfillment"
    AMOUNT_MISMATCH = "amount_mismatch"
    DUPLICATE_PROVIDER_TRANSACTION = "duplicate_provider_transaction"
    REFUND_MISMATCH = "refund_mismatch"


class ReconciliationReport(Base):
    """
    Summary record of an automated or manual financial reconciliation audit scan.
    """
    __tablename__ = "reconciliation_reports"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    total_payments_checked = Column(Integer, default=0, nullable=False)
    total_orders_checked = Column(Integer, default=0, nullable=False)
    total_wallet_tx_checked = Column(Integer, default=0, nullable=False)
    discrepancies_count = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="clean", nullable=False) # clean, discrepancies_found
    summary_json = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    discrepancies = relationship("ReconciliationDiscrepancy", back_populates="report", cascade="all, delete-orphan")


class ReconciliationDiscrepancy(Base):
    """
    Individual audit anomaly detected by the reconciliation engine.
    """
    __tablename__ = "reconciliation_discrepancies"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    report_id = Column(BigInteger, ForeignKey("reconciliation_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    discrepancy_type = Column(String(64), nullable=False, index=True)
    order_id = Column(BigInteger, nullable=True, index=True)
    payment_id = Column(BigInteger, nullable=True, index=True)
    expected_value = Column(String(128), nullable=True)
    actual_value = Column(String(128), nullable=True)
    details = Column(Text, nullable=True)
    is_resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_by = Column(BigInteger, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    report = relationship("ReconciliationReport", back_populates="discrepancies")
