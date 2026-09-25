from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.notification import InAppNotification

logger = get_logger(__name__)


class NotificationService:
    @classmethod
    async def create_notification(
        cls,
        session: AsyncSession,
        user_id: int,
        type_: str,
        title: str,
        message: str,
        related_entity: str | None = None,
    ) -> InAppNotification:
        """Creates an in-app notification entry for the user."""
        notif = InAppNotification(
            user_id=user_id,
            type=type_,
            title=title,
            message=message,
            related_entity=related_entity,
            is_read=False,
            created_at=utc_now(),
        )
        session.add(notif)
        await session.commit()
        await session.refresh(notif)
        return notif

    @classmethod
    async def list_notifications(cls, session: AsyncSession, user_id: int, limit: int = 50) -> list[InAppNotification]:
        res = await session.execute(
            select(InAppNotification)
            .where(InAppNotification.user_id == user_id)
            .order_by(desc(InAppNotification.created_at))
            .limit(limit)
        )
        return list(res.scalars().all())

    @classmethod
    async def mark_as_read(cls, session: AsyncSession, notification_id: int, user_id: int) -> bool:
        notif = await session.get(InAppNotification, notification_id)
        if notif and notif.user_id == user_id:
            notif.is_read = True
            await session.commit()
            return True
        return False

    @classmethod
    async def mark_all_as_read(cls, session: AsyncSession, user_id: int) -> int:
        from sqlalchemy import update

        res = await session.execute(
            update(InAppNotification)
            .where(InAppNotification.user_id == user_id, InAppNotification.is_read == False)
            .values(is_read=True)
        )
        await session.commit()
        return res.rowcount


notification_service = NotificationService()
