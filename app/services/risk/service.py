from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.order import Order, OrderStatus
from app.models.risk import RiskAudit, RiskSeverity, RiskType
from app.models.user import User

logger = get_logger(__name__)


class RiskService:
    @staticmethod
    async def log_risk_event(
        session: AsyncSession,
        user_id: int,
        risk_type: str,
        severity: str = RiskSeverity.MEDIUM.value,
        details: Optional[str] = None,
        flag_user: bool = False,
    ) -> RiskAudit:
        """Logs a suspicious activity event and optionally flags the user."""
        audit = RiskAudit(
            user_id=user_id,
            risk_type=risk_type,
            severity=severity,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)

        if flag_user:
            user = await session.get(User, user_id)
            if user:
                user.is_flagged_for_abuse = True

        await session.flush()
        logger.warning(f"Risk event logged: [{severity.upper()}] {risk_type} for user {user_id}: {details}")
        return audit

    @staticmethod
    async def check_referral_velocity(session: AsyncSession, referrer_id: int) -> bool:
        """
        Prevents referral abuse (bot farms / synthetic users).
        Returns False if velocity limit (> 10 referrals in 1 hour) is exceeded.
        """
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        count = (
            await session.scalar(
                select(func.count(User.id)).where(
                    and_(User.referrer_id == referrer_id, User.created_at >= one_hour_ago)
                )
            )
            or 0
        )

        if count >= 10:
            await RiskService.log_risk_event(
                session=session,
                user_id=referrer_id,
                risk_type=RiskType.REFERRAL_VELOCITY.value,
                severity=RiskSeverity.HIGH.value,
                details=f"Referral velocity exceeded: {count} referrals within 1 hour.",
            )
            return False
        return True

    @staticmethod
    async def check_checkout_spam(session: AsyncSession, user_id: int) -> bool:
        """
        Prevents checkout spam (creating dozens of unpaid orders).
        Returns False if user has > 10 unpaid/created orders in the last 15 minutes.
        """
        fifteen_min_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
        count = (
            await session.scalar(
                select(func.count(Order.id)).where(
                    and_(
                        Order.user_id == user_id,
                        Order.status.in_([OrderStatus.CREATED.value, OrderStatus.AWAITING_PAYMENT.value]),
                        Order.created_at >= fifteen_min_ago,
                    )
                )
            )
            or 0
        )

        if count >= 10:
            await RiskService.log_risk_event(
                session=session,
                user_id=user_id,
                risk_type=RiskType.CHECKOUT_SPAM.value,
                severity=RiskSeverity.MEDIUM.value,
                details=f"Checkout spam detected: {count} pending orders in last 15 minutes.",
            )
            return False
        return True


risk_service = RiskService()
