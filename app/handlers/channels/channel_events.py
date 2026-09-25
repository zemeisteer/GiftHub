from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatJoinRequest, ChatMemberUpdated

from app.core.logging import get_logger
from data import config
from database import queries
from database.db import AsyncSessionLocal

logger = get_logger(__name__)

router = Router()


@router.my_chat_member()
async def on_bot_chat_member_updated(event: ChatMemberUpdated):
    """
    Auto-detects when the bot is added as an administrator to a channel or group.
    Fulfills TZ requirement 3.4 (Yangi kanal qo'shish oqimi / my_chat_member).
    """
    chat = event.chat
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    if new_status in [ChatMemberStatus.ADMINISTRATOR] and old_status not in [ChatMemberStatus.ADMINISTRATOR]:
        title = chat.title or "Noma'lum Kanal"
        bot = event.bot
        invite_link = f"@{chat.username}" if chat.username else f"https://t.me/c/{str(chat.id).replace('-100', '')}"
        if not chat.username:
            try:
                exported = await bot.export_chat_invite_link(chat.id)
                if exported:
                    invite_link = exported
            except Exception as e:
                logger.debug(f"Kanal taklif havolasini olishda ogohlantirish ({chat.id}): {e}")

        is_join_req = ("+" in invite_link) or ("joinchat" in invite_link)
        is_group = chat.type in ["group", "supergroup"]
        default_req_type = "join_request" if is_join_req else ("group" if is_group else "ordinary")

        async with AsyncSessionLocal() as session:
            # Register as newly detected channel awaiting admin confirmation
            await queries.add_or_update_channel(
                session=session,
                username_or_link=invite_link,
                title=title,
                req_type=default_req_type,
                chat_id=chat.id,
                is_detected=True,
                is_active=False,
            )

        # Notify admins
        for admin_id_str in config.ADMINS:
            try:
                admin_id = int(admin_id_str)
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"📣 <b>Bot yangi kanal yoki guruhga admin qilindi!</b>\n\n"
                        f"Nomi: <b>{title}</b>\n"
                        f"Havola: {invite_link}\n"
                        f"Chat ID: <code>{chat.id}</code>\n"
                        f"Shart turi: <b>{default_req_type}</b>\n\n"
                        f"⚙️ <i>Admin paneldan majburiy a'zolik turini tanlab, 'Tayyor' tugmasini bosing!</i>"
                    ),
                )
            except Exception as e:
                logger.warning(f"Adminga ({admin_id_str}) yangi kanal bildirishnomasini yuborishda xatolik: {e}")


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest):
    """
    Handles join requests for private channels with join-request requirements.
    Fulfills TZ requirement 3.4 (So'rov orqali qo'shilish).
    """
    try:
        async with AsyncSessionLocal() as session:
            await queries.record_user_join_request(session=session, user_id=event.from_user.id, chat_id=event.chat.id)
    except Exception as e:
        logger.error(f"Join request yozishda xatolik (user: {event.from_user.id}, chat: {event.chat.id}): {e}")
