from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.models.broadcast import BroadcastDraft
from data import config
from database import queries
from database.db import AsyncSessionLocal

router = Router()

def is_admin_check(user_id: int) -> bool:
    return str(user_id) in config.ADMINS

@router.message(F.forward_origin)
async def handle_admin_forward(message: Message):
    """
    Handles forwarded messages by admins:
    1. If forwarded from a user -> Admin nomination candidate flow (TZ 3.7)
    2. If forwarded from a channel/bot -> Broadcast draft intake (TZ 3.5)
    """
    if not is_admin_check(message.from_user.id):
        return

    origin = message.forward_origin
    origin_type = origin.type

    # Forwarded from User or Bot
    if origin_type == "user":
        sender = origin.sender_user
        uid = sender.id
        name = sender.full_name
        uname = f"@{sender.username}" if sender.username else "mavjud emas"

        # If forwarded from a bot (like @PostBot)
        if getattr(sender, "is_bot", False) or "bot" in uname.lower():
            async with AsyncSessionLocal() as session:
                draft = BroadcastDraft(
                    mode="postbot",
                    text=message.text or message.caption or "",
                    forward_chat_id=message.chat.id,
                    forward_message_id=message.message_id
                )
                session.add(draft)
                await session.commit()
                draft_id = draft.id

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Barcha foydalanuvchilarga tarqatish", callback_data=f"send_bc_draft:{draft_id}")],
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_adm")]
            ])

            await message.reply(
                text=(
                    f"🤖 <b>PostBot / Reklama posti qabul qilindi!</b>\n\n"
                    f"Manba boti: <b>{name}</b> ({uname})\n"
                    f"Xabar ID: <code>{message.message_id}</code>\n"
                    f"Tugmalar va formatlash: <i>Saqlab qolindi</i>\n\n"
                    f"Ushbu reklamani barcha foydalanuvchilarga tarqatishni xohlaysizmi?"
                ),
                reply_markup=kb
            )
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💎 Super Admin", callback_data=f"make_adm:{uid}:super_admin"),
                InlineKeyboardButton(text="₮ Narx Admin", callback_data=f"make_adm:{uid}:price_admin")
            ],
            [
                InlineKeyboardButton(text="🛟 Support Admin", callback_data=f"make_adm:{uid}:support_admin"),
                InlineKeyboardButton(text="📣 Marketing Admin", callback_data=f"make_adm:{uid}:marketing_admin")
            ],
            [
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_adm")
            ]
        ])

        await message.reply(
            text=(
                f"👤 <b>Adminlikka nomzod aniqlandi!</b>\n\n"
                f"Ism: <b>{name}</b>\n"
                f"Username: {uname}\n"
                f"User ID: <code>{uid}</code>\n\n"
                f"Ushbu foydalanuvchiga qaysi rolni bermoqchisiz?"
            ),
            reply_markup=kb
        )

    # Forwarded from Channel or Chat
    elif origin_type in ["channel", "chat"]:
        chat = getattr(origin, "chat", None)
        title = chat.title if chat else "Kanal"
        msg_id = getattr(origin, "message_id", message.message_id)

        async with AsyncSessionLocal() as session:
            draft = BroadcastDraft(
                mode="forward",
                text=message.text or message.caption or "",
                forward_chat_id=message.chat.id,
                forward_message_id=message.message_id
            )
            session.add(draft)
            await session.commit()
            draft_id = draft.id

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Barcha foydalanuvchilarga yuborish", callback_data=f"send_bc_draft:{draft_id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_adm")]
        ])

        await message.reply(
            text=(
                f"📥 <b>Broadcast uchun post qabul qilindi!</b>\n\n"
                f"Manba: <b>{title}</b>\n"
                f"Xabar ID: <code>{msg_id}</code>\n\n"
                f"Ushbu xabarni barcha foydalanuvchilarga copyMessage orqali tarqatishni xohlaysizmi?"
            ),
            reply_markup=kb
        )

@router.message(F.text)
async def handle_admin_postbot_code(message: Message):
    """
    Handles PostBot share codes or links sent by admins directly.
    """
    if not is_admin_check(message.from_user.id):
        return

    txt = (message.text or "").strip()
    if "@PostBot" in txt or "t.me/postbot" in txt.lower() or "postbot" in txt.lower():
        async with AsyncSessionLocal() as session:
            draft = BroadcastDraft(
                mode="postbot",
                text=txt,
                forward_chat_id=message.chat.id,
                forward_message_id=message.message_id
            )
            session.add(draft)
            await session.commit()
            draft_id = draft.id

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Barcha foydalanuvchilarga yuborish", callback_data=f"send_bc_draft:{draft_id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_adm")]
        ])

        await message.reply(
            text=(
                f"🤖 <b>PostBot kodi / xabari qabul qilindi!</b>\n\n"
                f"Kod / Matn: <code>{txt[:120]}</code>\n\n"
                f"💡 <i>Ushbu xabarni bot orqali barcha foydalanuvchilarga tarqatishni xohlaysizmi?</i>"
            ),
            reply_markup=kb
        )

@router.callback_query(F.data.startswith("send_bc_"))
async def cb_send_broadcast_flow(callback: CallbackQuery):
    if not is_admin_check(callback.from_user.id):
        await callback.answer("Ruxsat berilmagan!", show_alert=True)
        return

    parts = callback.data.split(":")
    tag = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    import asyncio

    from app.web.server import BroadcastRequest
    from database.models import BroadcastDraft

    target_chat_id = callback.message.chat.id
    target_msg_id = None

    if tag == "send_bc_draft":
        draft_id = int(arg)
        async with AsyncSessionLocal() as session:
            draft = await session.get(BroadcastDraft, draft_id)
            if draft and draft.forward_message_id:
                target_chat_id = draft.forward_chat_id or callback.message.chat.id
                target_msg_id = draft.forward_message_id
    elif tag == "send_bc_fwd":
        target_msg_id = int(arg)

    if not target_msg_id:
        target_msg_id = callback.message.reply_to_message.message_id if callback.message.reply_to_message else callback.message.message_id

    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session, segment="all")

    if not recipients:
        await callback.message.edit_text("⚠️ Reklama yuborish uchun foydalanuvchilar topilmadi.")
        return

    await callback.message.edit_text(
        f"⏳ <b>Broadcast boshlandi!</b>\n\n"
        f"👥 Qabul qiluvchilar: <b>{len(recipients)} ta foydalanuvchi</b>\n"
        f"⚡ Tezlik: ~25-30 xabar/sekund\n\n"
        f"<i>Tugagach hisobot yuboriladi...</i>"
    )

    req = BroadcastRequest(
        segment="all",
        mode="postbot",
        forward_mode=False
    )
    # Trigger background queue
    bot = callback.bot
    async def _send_copy_queue():
        sent = 0
        blocked = 0
        failed = 0
        for uid in recipients:
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=target_chat_id, message_id=target_msg_id)
                sent += 1
            except Exception as e:
                err_str = str(e).lower()
                if "forbidden" in err_str or "blocked" in err_str:
                    blocked += 1
                else:
                    failed += 1
            await asyncio.sleep(0.04)

        try:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=(
                    f"✅ <b>Broadcast muvaffaqiyatli yakunlandi!</b>\n\n"
                    f"📊 Jami rejalashtirilgan: <b>{len(recipients)}</b>\n"
                    f"✅ Yetkazildi: <b>{sent}</b>\n"
                    f"🚫 Botni bloklagan: <b>{blocked}</b>\n"
                    f"⚠️ Xatoliklar: <b>{failed}</b>"
                )
            )
        except Exception:
            pass

    asyncio.create_task(_send_copy_queue())

@router.callback_query(F.data.startswith("make_adm:"))
async def cb_assign_admin(callback: CallbackQuery):
    parts = callback.data.split(":")
    uid = int(parts[1])
    role = parts[2]

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, uid)
        if not user:
            user = await queries.get_or_create_user(
                session=session,
                user_id=uid,
                first_name=f"Admin {uid}"
            )

        await queries.set_user_role(session, uid, role)
        await queries.log_admin_action(
            session=session,
            admin_id=callback.from_user.id,
            admin_username=callback.from_user.username,
            action=f"Yangi admin tayinladi (Forward orqali): ID {uid}",
            details=f"Rol: {role}"
        )

    await callback.message.edit_text(
        text=f"✅ Foydalanuvchi (ID: <code>{uid}</code>) muvaffaqiyatli <b>{role}</b> etib tayinlandi!"
    )

@router.callback_query(F.data == "cancel_adm")
async def cb_cancel_adm(callback: CallbackQuery):
    await callback.message.edit_text("Amal bekor qilindi.")
