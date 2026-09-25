from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientBalanceError, UserNotFoundError
from app.core.logging import get_logger
from app.models.audit import AdminAuditLog
from app.models.user import User
from app.models.wallet import Transaction, WalletTransaction

logger = get_logger(__name__)


class WalletService:
    @staticmethod
    async def get_user_locked(session: AsyncSession, user_id: int) -> User:
        """Fetches user with row-level lock (with_for_update) to prevent race conditions."""
        stmt = select(User).where(User.id == user_id).with_for_update()
        res = await session.execute(stmt)
        user = res.scalars().first()
        if not user:
            raise UserNotFoundError(f"Foydalanuvchi topilmadi: {user_id}")
        return user

    @classmethod
    async def credit_balance(
        cls,
        session: AsyncSession,
        user_id: int,
        amount: Decimal,
        tx_type: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        note: str | None = None,
        meta_info: str | None = None,
    ) -> tuple[User, WalletTransaction]:
        """
        Atomically credits a user's wallet and creates an immutable ledger entry.
        """
        if amount <= Decimal("0.00"):
            raise ValueError("Kredit summasi musbat bo'lishi shart.")

        user = await cls.get_user_locked(session, user_id)
        balance_before = Decimal(str(user.balance))
        balance_after = balance_before + amount
        user.balance = balance_after

        # 1. Immutable ledger entry
        wallet_tx = WalletTransaction(
            user_id=user_id,
            tx_type=tx_type,
            amount=amount,
            currency="UZS",
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id) if reference_id else None,
            note=note,
            meta_info=meta_info,
        )
        session.add(wallet_tx)

        # 2. Legacy transaction record
        legacy_tx = Transaction(
            user_id=user_id,
            amount=amount,
            tx_type=tx_type,
            method=reference_type or "system",
            status="success",
            note=note,
        )
        session.add(legacy_tx)
        await session.flush()

        logger.info(
            f"[Wallet Credit] user={user_id}, amount={amount} UZS, "
            f"before={balance_before}, after={balance_after}, type={tx_type}"
        )
        return user, wallet_tx

    @classmethod
    async def debit_balance(
        cls,
        session: AsyncSession,
        user_id: int,
        amount: Decimal,
        tx_type: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        note: str | None = None,
        meta_info: str | None = None,
    ) -> tuple[User, WalletTransaction]:
        """
        Atomically debits a user's wallet with balance validation and creates a ledger entry.
        """
        if amount <= Decimal("0.00"):
            raise ValueError("Yechib olish summasi musbat bo'lishi shart.")

        user = await cls.get_user_locked(session, user_id)
        balance_before = Decimal(str(user.balance))

        if balance_before < amount:
            raise InsufficientBalanceError(
                f"Balansingizda mablag' yetarli emas! Joriy balans: {balance_before:,.0f} so'm, talab qilinadi: {amount:,.0f} so'm"
            )

        balance_after = balance_before - amount
        user.balance = balance_after

        # 1. Immutable ledger entry (amount recorded as negative for debits)
        wallet_tx = WalletTransaction(
            user_id=user_id,
            tx_type=tx_type,
            amount=-amount,
            currency="UZS",
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id) if reference_id else None,
            note=note,
            meta_info=meta_info,
        )
        session.add(wallet_tx)

        # 2. Legacy transaction record
        legacy_tx = Transaction(
            user_id=user_id, amount=-amount, tx_type=tx_type, method="balance", status="success", note=note
        )
        session.add(legacy_tx)
        await session.flush()

        logger.info(
            f"[Wallet Debit] user={user_id}, amount={amount} UZS, "
            f"before={balance_before}, after={balance_after}, type={tx_type}"
        )
        return user, wallet_tx

    @classmethod
    async def adjust_balance_admin(
        cls,
        session: AsyncSession,
        admin_id: int,
        user_id: int,
        amount: Decimal,
        reason: str,
        admin_username: str | None = None,
    ) -> tuple[User, WalletTransaction]:
        """
        Allows an administrator to safely adjust a user's balance with an audit log.
        """
        if amount > Decimal("0.00"):
            user, tx = await cls.credit_balance(
                session=session,
                user_id=user_id,
                amount=amount,
                tx_type="admin_adjustment",
                reference_type="admin",
                reference_id=str(admin_id),
                note=f"Admin tomonidan tuzatish: {reason}",
            )
        elif amount < Decimal("0.00"):
            user, tx = await cls.debit_balance(
                session=session,
                user_id=user_id,
                amount=abs(amount),
                tx_type="admin_adjustment",
                reference_type="admin",
                reference_id=str(admin_id),
                note=f"Admin tomonidan yechildi: {reason}",
            )
        else:
            user = await cls.get_user_locked(session, user_id)
            return user, None

        # Immutable Admin Audit Log
        audit = AdminAuditLog(
            admin_id=admin_id,
            admin_username=admin_username,
            action="adjust_balance",
            entity_type="user",
            entity_id=str(user_id),
            old_value=str(tx.balance_before),
            new_value=str(tx.balance_after),
            reason=reason,
            details=f"Balans {amount:+,.0f} so'mga o'zgartirildi",
        )
        session.add(audit)
        return user, tx


wallet_service = WalletService()
