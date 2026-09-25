from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GiftHubException
from app.core.logging import get_logger
from app.models.base import utc_now
from app.models.support import SupportTicket, TicketMessage, TicketStatus

logger = get_logger(__name__)


class SupportService:
    @classmethod
    async def create_ticket(
        cls,
        session: AsyncSession,
        user_id: int,
        subject: str,
        category: str = "other",
        initial_message: str | None = None,
        order_id: int | None = None,
    ) -> SupportTicket:
        """Creates a new support ticket and attaches initial message if provided."""
        ticket = SupportTicket(
            user_id=user_id,
            order_id=order_id,
            category=category,
            subject=subject.strip(),
            status=TicketStatus.OPEN,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(ticket)
        await session.flush()

        if initial_message and initial_message.strip():
            msg = TicketMessage(
                ticket_id=ticket.id,
                sender_id=user_id,
                sender_type="user",
                text=initial_message.strip(),
                created_at=utc_now(),
            )
            session.add(msg)

        await session.commit()
        await session.refresh(ticket)
        logger.info(f"[Support Ticket Created] id={ticket.id}, user={user_id}, category={category}")
        return ticket

    @classmethod
    async def add_reply(
        cls, session: AsyncSession, ticket_id: int, sender_id: int, sender_type: str, text: str
    ) -> TicketMessage:
        """Adds a reply message to a support ticket."""
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            raise GiftHubException("Murojaat topilmadi", code="TICKET_NOT_FOUND", status_code=404)

        now = utc_now()
        msg = TicketMessage(
            ticket_id=ticket_id, sender_id=sender_id, sender_type=sender_type, text=text.strip(), created_at=now
        )
        session.add(msg)

        if sender_type == "admin":
            ticket.status = TicketStatus.IN_PROGRESS
        ticket.updated_at = now

        await session.commit()
        await session.refresh(msg)
        return msg

    @classmethod
    async def update_status(
        cls, session: AsyncSession, ticket_id: int, status: str, assigned_admin_id: int | None = None
    ) -> SupportTicket:
        """Updates ticket status (OPEN, IN_PROGRESS, RESOLVED, CLOSED)."""
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            raise GiftHubException("Murojaat topilmadi", code="TICKET_NOT_FOUND", status_code=404)

        ticket.status = status
        if assigned_admin_id is not None:
            ticket.assigned_admin_id = assigned_admin_id
        ticket.updated_at = utc_now()

        await session.commit()
        await session.refresh(ticket)
        return ticket

    @classmethod
    async def list_user_tickets(cls, session: AsyncSession, user_id: int) -> list[SupportTicket]:
        res = await session.execute(
            select(SupportTicket).where(SupportTicket.user_id == user_id).order_by(desc(SupportTicket.created_at))
        )
        return list(res.scalars().all())

    @classmethod
    async def list_all_tickets(
        cls, session: AsyncSession, status: str | None = None, limit: int = 50
    ) -> list[SupportTicket]:
        query = select(SupportTicket).order_by(desc(SupportTicket.updated_at))
        if status:
            query = query.where(SupportTicket.status == status)
        res = await session.execute(query.limit(limit))
        return list(res.scalars().all())


support_service = SupportService()
