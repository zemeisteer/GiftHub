from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.order import Order, OrderStatus
from app.models.payment import PaymentTransaction
from app.models.reconciliation import DiscrepancyType, ReconciliationDiscrepancy, ReconciliationReport
from app.models.wallet import WalletTransaction

logger = get_logger(__name__)


class ReconciliationService:
    @staticmethod
    async def run_reconciliation_audit(session: AsyncSession) -> ReconciliationReport:
        """
        Runs comprehensive automated comparison across:
        Payment Providers (PaymentTransaction) <-> Orders <-> Wallet Ledger (WalletTransaction).
        """
        now = datetime.now(timezone.utc)
        discrepancies: List[ReconciliationDiscrepancy] = []

        # 1. Total counts
        p_count = await session.scalar(select(func.count(PaymentTransaction.id))) or 0
        o_count = await session.scalar(select(func.count(Order.id))) or 0
        w_count = await session.scalar(select(func.count(WalletTransaction.id))) or 0

        # --- Check 1: Paid Payment but Unpaid Order ---
        stmt_1 = (
            select(PaymentTransaction, Order)
            .join(Order, PaymentTransaction.order_id == Order.id)
            .where(
                and_(
                    PaymentTransaction.status == "success",
                    Order.status.in_([OrderStatus.CREATED.value, OrderStatus.AWAITING_PAYMENT.value])
                )
            )
        )
        res_1 = await session.execute(stmt_1)
        for pt, o in res_1.all():
            discrepancies.append(
                ReconciliationDiscrepancy(
                    discrepancy_type=DiscrepancyType.PAID_PAYMENT_UNPAID_ORDER.value,
                    order_id=o.id,
                    payment_id=pt.id,
                    expected_value=OrderStatus.PAID.value,
                    actual_value=o.status,
                    details=f"Payment #{pt.id} ({pt.provider}) muvaffaqiyatli to'langan, lekin Buyurtma #{o.id} '{o.status}' holatida qolib ketgan.",
                    is_resolved=False,
                    created_at=now
                )
            )

        # --- Check 2: Paid Order (Wallet) but Missing Wallet Ledger Entry ---
        stmt_2 = (
            select(Order)
            .where(
                and_(
                    Order.status.in_([OrderStatus.PAID.value, OrderStatus.COMPLETED.value, OrderStatus.PROCESSING.value]),
                    Order.payment_method.in_(["balance", "wallet"])
                )
            )
        )
        res_2 = await session.execute(stmt_2)
        paid_wallet_orders = list(res_2.scalars().all())

        for o in paid_wallet_orders:
            w_stmt = select(WalletTransaction.id).where(
                and_(
                    WalletTransaction.reference_type == "order",
                    WalletTransaction.reference_id == str(o.id),
                    WalletTransaction.tx_type == "purchase"
                )
            ).limit(1)
            w_exists = await session.scalar(w_stmt)
            if not w_exists:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        discrepancy_type=DiscrepancyType.PAID_ORDER_MISSING_WALLET_TX.value,
                        order_id=o.id,
                        expected_value=f"Debit {o.total_price} UZS",
                        actual_value="Missing ledger entry",
                        details=f"Hamyondan to'langan Buyurtma #{o.id} uchun hamyon ledger yozuvi (WalletTransaction) topilmadi.",
                        is_resolved=False,
                        created_at=now
                    )
                )

        # --- Check 3: Paid Order Missing Fulfillment (Stuck > 5 minutes) ---
        five_min_ago = now - timedelta(minutes=5)
        stmt_3 = (
            select(Order)
            .where(
                and_(
                    Order.status == OrderStatus.PAID.value,
                    Order.paid_at.is_not(None),
                    Order.paid_at < five_min_ago,
                    Order.fulfillment_status.in_(["pending", "failed"])
                )
            )
        )
        res_3 = await session.execute(stmt_3)
        for o in res_3.scalars().all():
            discrepancies.append(
                ReconciliationDiscrepancy(
                    discrepancy_type=DiscrepancyType.PAID_ORDER_MISSING_FULFILLMENT.value,
                    order_id=o.id,
                    expected_value="fulfilled",
                    actual_value=o.fulfillment_status,
                    details=f"Buyurtma #{o.id} to'langan, lekin 5 daqiqadan ko'proq vaqt davomida yetkazib berilmagan ({o.fulfillment_status}).",
                    is_resolved=False,
                    created_at=now
                )
            )

        # --- Check 4: Amount Mismatch (Payment Amount != Order Total) ---
        stmt_4 = (
            select(PaymentTransaction, Order)
            .join(Order, PaymentTransaction.order_id == Order.id)
            .where(
                and_(
                    PaymentTransaction.status == "success",
                    PaymentTransaction.amount != Order.total_price
                )
            )
        )
        res_4 = await session.execute(stmt_4)
        for pt, o in res_4.all():
            discrepancies.append(
                ReconciliationDiscrepancy(
                    discrepancy_type=DiscrepancyType.AMOUNT_MISMATCH.value,
                    order_id=o.id,
                    payment_id=pt.id,
                    expected_value=str(o.total_price),
                    actual_value=str(pt.amount),
                    details=f"To'lov summasi ({pt.amount} UZS) buyurtma summasiga ({o.total_price} UZS) mos kelmadi.",
                    is_resolved=False,
                    created_at=now
                )
            )

        # --- Check 5: Duplicate Provider Transaction / Multiple Success for One Order ---
        stmt_5 = (
            select(PaymentTransaction.order_id, func.count(PaymentTransaction.id).label("cnt"))
            .where(
                and_(
                    PaymentTransaction.status == "success",
                    PaymentTransaction.order_id.is_not(None)
                )
            )
            .group_by(PaymentTransaction.order_id)
            .having(func.count(PaymentTransaction.id) > 1)
        )
        res_5 = await session.execute(stmt_5)
        for oid, cnt in res_5.all():
            discrepancies.append(
                ReconciliationDiscrepancy(
                    discrepancy_type=DiscrepancyType.DUPLICATE_PROVIDER_TRANSACTION.value,
                    order_id=oid,
                    expected_value="1 successful payment",
                    actual_value=f"{cnt} successful payments",
                    details=f"Buyurtma #{oid} uchun {cnt} ta muvaffaqiyatli to'lov tranzaksiyasi aniqlandi!",
                    is_resolved=False,
                    created_at=now
                )
            )

        # Create report record
        status_str = "clean" if len(discrepancies) == 0 else "discrepancies_found"
        report = ReconciliationReport(
            total_payments_checked=p_count,
            total_orders_checked=o_count,
            total_wallet_tx_checked=w_count,
            discrepancies_count=len(discrepancies),
            status=status_str,
            summary_json={
                "checked_at": now.isoformat(),
                "discrepancies_found": len(discrepancies)
            },
            created_at=now
        )
        session.add(report)
        await session.flush()

        for d in discrepancies:
            d.report_id = report.id
            session.add(d)

        await session.flush()
        logger.info(f"Reconciliation audit finished: {p_count} payments, {o_count} orders checked. {len(discrepancies)} discrepancies found.")
        return report

    @staticmethod
    async def get_dashboard_stats(session: AsyncSession) -> Dict[str, Any]:
        """Provides financial dashboard aggregations for Admin Panel."""
        # Payments received
        pay_res = await session.execute(
            select(
                PaymentTransaction.provider,
                func.count(PaymentTransaction.id).label("count"),
                func.coalesce(func.sum(PaymentTransaction.amount), 0).label("total")
            )
            .where(PaymentTransaction.status == "success")
            .group_by(PaymentTransaction.provider)
        )
        payments_by_provider = {r[0]: {"count": r[1], "total": float(r[2])} for r in pay_res.all()}

        # Total wallet deposits vs purchases
        w_res = await session.execute(
            select(
                WalletTransaction.tx_type,
                func.count(WalletTransaction.id).label("count"),
                func.coalesce(func.sum(WalletTransaction.amount), 0).label("total")
            )
            .group_by(WalletTransaction.tx_type)
        )
        wallet_by_type = {r[0]: {"count": r[1], "total": float(r[2])} for r in w_res.all()}

        # Paid vs Fulfilled orders
        paid_orders_count = await session.scalar(
            select(func.count(Order.id)).where(Order.status.in_([OrderStatus.PAID.value, OrderStatus.COMPLETED.value]))
        ) or 0
        fulfilled_orders_count = await session.scalar(
            select(func.count(Order.id)).where(Order.fulfillment_status == "fulfilled")
        ) or 0
        refunded_orders_count = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.REFUNDED.value)
        ) or 0

        # Unresolved discrepancies
        unresolved_disc_count = await session.scalar(
            select(func.count(ReconciliationDiscrepancy.id)).where(ReconciliationDiscrepancy.is_resolved == False)
        ) or 0

        return {
            "payments_by_provider": payments_by_provider,
            "wallet_breakdown": wallet_by_type,
            "orders": {
                "paid_count": paid_orders_count,
                "fulfilled_count": fulfilled_orders_count,
                "refunded_count": refunded_orders_count
            },
            "unresolved_discrepancies": unresolved_disc_count
        }


reconciliation_service = ReconciliationService()
