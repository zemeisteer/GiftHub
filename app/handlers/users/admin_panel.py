import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func

from database.db import AsyncSessionLocal
from database.models import User, Order, Transaction, ChannelRequirement
from database import queries
from data import config
from app.state.admin_states import AdminBroadcastState
from app.keyboards.admin_keyboards import (
    get_admin_main_keyboard,
    get_admin_orders_keyboard,
    get_admin_order_action_keyboard,
    get_admin_channels_keyboard,
    get_admin_back_keyboard
)
from app.keyboards.shop_keyboards import get_back_to_main_keyboard

router = Router()
logger = logging.getLogger(__name__)

async def is_admin_user(user_id: int, session) -> bool:
    if str(user_id) in config.ADMINS:
        return True
    user = await queries.get_user_by_id(session, user_id)
    return bool(user and user.role != "user")


@router.message(Command(commands=["panel", "admin"]))
async def cmd_admin(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            # Only for admins - ignore silently for normal users
            return

    admin_url = config.get_admin_app_url() if hasattr(config, "get_admin_app_url") else config.ADMIN_APP_URL
    buttons = []
    if admin_url and admin_url.startswith("https://"):
        buttons.append([
            InlineKeyboardButton(text="⚙️ Admin Panelni ochish (Web App)", web_app=WebAppInfo(url=admin_url))
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="⚙️ Admin Panelni ochish (Web App)", url=admin_url or "https://t.me")
        ])
    buttons.append([
        InlineKeyboardButton(text="📊 Bot ichida ko'rish", callback_data="admin:menu")
    ])

    await message.answer(
        "⚙️ <b>GiftHub (Stellar) — Boshqaruv Paneli (Admin Panel)</b>\n\n"
        "Narxlar, buyurtmalar, yangi xizmatlar, majburiy obuna va statistikani "
        "boshqarish uchun quyidagi tugmani bosing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "admin:menu")
async def show_admin_dashboard(event, state: FSMContext = None):
    if state:
        await state.clear()
    user_id = event.from_user.id

    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            msg = "⛔ <b>Kechirasiz!</b> Bu bo'lim faqat bot ma'murlari uchun mo'ljallangan."
            if isinstance(event, CallbackQuery):
                await event.answer("Ruxsat berilmagan!", show_alert=True)
            else:
                await event.answer(msg)
            return

        # Fetch basic stats
        total_users = await session.scalar(select(func.count(User.id)))
        total_orders = await session.scalar(select(func.count(Order.id)))
        pending_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "pending"))
        total_revenue = await session.scalar(select(func.sum(Order.total_price)).where(Order.status == "done")) or 0.0

    text = (
        "⚙️ <b>GiftHub — Administrator Boshqaruv Paneli</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users:,} ta</b>\n"
        f"📦 Jami buyurtmalar: <b>{total_orders:,} ta</b>\n"
        f"⏳ Kutilayotgan xaridlar: <b>{pending_orders:,} ta</b>\n"
        f"💰 Muvaffaqiyatli savdo: <b>{total_revenue:,.0f} so'm</b>\n\n"
        "Boshqarish uchun quyidagi bo'limlardan birini tanlang:"
    )

    kb = get_admin_main_keyboard()
    if isinstance(event, CallbackQuery):
        from aiogram.exceptions import TelegramBadRequest
        try:
            await event.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
        except Exception:
            await event.message.answer(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


# ================= ADMIN STATS ================= #

@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return

        total_users = await session.scalar(select(func.count(User.id)))
        active_buyers = await session.scalar(select(func.count(func.distinct(Order.user_id))).where(Order.status == "done"))
        total_orders = await session.scalar(select(func.count(Order.id)))
        done_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "done"))
        total_revenue = await session.scalar(select(func.sum(Order.total_price)).where(Order.status == "done")) or 0.0
        total_cost = await session.scalar(select(func.sum(Order.cost_price)).where(Order.status == "done")) or 0.0
        profit = total_revenue - total_cost

    text = (
        "📊 <b>Loyiha to'liq statistikasi:</b>\n\n"
        f"👥 Barcha foydalanuvchilar: <b>{total_users:,} ta</b>\n"
        f"🛍 Xarid qilgan xaridorlar: <b>{active_buyers:,} ta</b>\n"
        f"📦 Barcha buyurtmalar: <b>{total_orders:,} ta</b>\n"
        f"✅ Bajarilgan buyurtmalar: <b>{done_orders:,} ta</b>\n"
        "────────────────────\n"
        f"💵 Jami tushum (savdo): <b>{total_revenue:,.0f} so'm</b>\n"
        f"📉 Xarajat (tannarx): <b>{total_cost:,.0f} so'm</b>\n"
        f"📈 Sof foyda: <b>{profit:,.0f} so'm</b>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_back_keyboard())
    await callback.answer()


# ================= ADMIN ORDERS ================= #

@router.callback_query(F.data == "admin:orders")
async def cb_admin_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return
        orders = await queries.list_all_orders(session=session, limit=10)

    text = "📦 <b>Oxirgi buyurtmalar ro'yxati:</b>\n\nBatafsil ko'rish yoki holatini o'zgartirish uchun buyurtmani bosing:"
    from aiogram.exceptions import TelegramBadRequest
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_orders_keyboard(orders))
        await callback.answer("✅ Ro'yxat yangilandi!")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await callback.answer("✅ Ro'yxat eng so'nggi holatda!", show_alert=False)
        else:
            await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data.startswith("adm_ord:view:"))
async def cb_admin_order_detail(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        user = await queries.get_user_by_id(session, order.user_id)
        buyer_name = user.first_name if user else "Foydalanuvchi"

    text = (
        f"📦 <b>Buyurtma #{order.order_code}</b>\n\n"
        f"👤 Xaridor: <b>{buyer_name}</b> (ID: <code>{order.user_id}</code>)\n"
        f"🎁 Mahsulot: <b>{order.item_title}</b>\n"
        f"👤 Qabul qiluvchi: <b>@{order.recipient_username or 'noma\'lum'}</b>\n"
        f"💰 Narxi: <b>{order.total_price:,.0f} so'm</b>\n"
        f"📉 Tannarxi: <b>{order.cost_price:,.0f} so'm</b>\n"
        f"📊 Holati: <b>{order.status.upper()}</b>\n"
        f"📅 Sana: <code>{order.created_at.strftime('%d.%m.%Y %H:%M')}</code>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_admin_order_action_keyboard(order_id))
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_order_action_keyboard(order_id))
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ord:done:"))
async def cb_admin_order_mark_done(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_status(session, order_id, "done")
        if order:
            try:
                await bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"🎉 <b>Buyurtmangiz bajarildi!</b>\n\n"
                        f"🔖 Buyurtma kodi: <code>{order.order_code}</code>\n"
                        f"📦 Mahsulot: <b>{order.item_title}</b>\n"
                        f"Xaridingiz uchun rahmat!"
                    )
                )
            except Exception:
                pass

    await callback.answer("✅ Buyurtma bajarildi deb belgilandi!", show_alert=True)
    await cb_admin_orders(callback)


@router.callback_query(F.data.startswith("adm_ord:cancel:"))
async def cb_admin_order_cancel(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_status(session, order_id, "cancel")
        if order:
            try:
                await bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"❌ <b>Buyurtmangiz bekor qilindi.</b>\n\n"
                        f"🔖 Buyurtma kodi: <code>{order.order_code}</code>\n"
                        f"💰 <b>{order.total_price:,.0f} so'm</b> mablag' hisobingizga qaytarildi."
                    )
                )
            except Exception:
                pass

    await callback.answer("❌ Buyurtma bekor qilindi va pul qaytarildi!", show_alert=True)
    await cb_admin_orders(callback)


# ================= ADMIN CHANNELS ================= #

@router.callback_query(F.data == "admin:channels")
async def cb_admin_channels(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return
        channels = await queries.list_channels(session=session)

    text = (
        "📢 <b>Majburiy a'zolik kanallari:</b>\n\n"
        "Foydalanuvchilar botga kirganda quyidagi kanallarga a'zo bo'lishi talab etiladi:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_channels_keyboard(channels))
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_channels_keyboard(channels))
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ch:del:"))
async def cb_admin_channel_del(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        await queries.delete_channel(session, ch_id)

    await callback.answer("🗑 Kanal o'chirildi!", show_alert=True)
    await cb_admin_channels(callback)


@router.callback_query(F.data == "adm_ch:add")
async def cb_admin_channel_add(callback: CallbackQuery):
    text = (
        "➕ <b>Yangi majburiy kanal qo'shish:</b>\n\n"
        "1. Botni kanalingiz yoki guruhingizga <b>admin</b> qilib qo'shing.\n"
        "2. Bot avtomatik tarzda kanalni aniqlaydi va ro'yxatga oladi.\n"
        "3. Yoki /panel buyrug'i orqali Admin Web App'ga kirib, havola orqali kanal qo'shishingiz mumkin."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_back_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ch:view:"))
async def cb_admin_channel_view(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        ch = await queries.get_channel(session, ch_id)
    if not ch:
        await callback.answer("Kanal topilmadi!", show_alert=True)
        return

    st = "🟢 Faol" if ch.is_active else "🔴 Nofaol"
    text = (
        f"📢 <b>Kanal ma'lumotlari:</b>\n\n"
        f"📌 Nomi: <b>{ch.title}</b>\n"
        f"🔗 Havola: <code>{ch.username_or_link}</code>\n"
        f"📊 Turi: <b>{ch.req_type}</b>\n"
        f"⚙️ Holati: <b>{st}</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"adm_ch:del:{ch.id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Kanallarga qaytish", callback_data="admin:channels")
        ]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin:card")
async def cb_admin_card(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return
        cards = await queries.list_payment_cards(session)
        p = await queries.get_payment_settings(session)

    cards_text = ""
    if cards:
        for i, c in enumerate(cards, 1):
            st = "🟢 Faol" if c.is_active else "🔴 Nofaol"
            cards_text += f"{i}. <b>{c.bank_name}</b> ({c.card_type}) — {st}\n   <code>{c.card_number}</code> | {c.card_holder}\n\n"
    else:
        cards_text = "<i>Hozircha kartalar qo'shilmagan.</i>\n\n"

    master_st = "🟢 Yoqilgan" if (p and p.card_active) else "🔴 O'chirilgan"

    text = (
        "💳 <b>Bank kartalari sozlamalari (P2P)</b>\n\n"
        f"Karta to'lovlari umumiy holati: <b>{master_st}</b>\n\n"
        f"{cards_text}"
        "💡 <i>Kartalarni qo'shish, tahrirlash va o'chirish uchun /panel buyrug'i orqali Admin Web App'dan foydalaning.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_back_keyboard())
    await callback.answer()


# ================= ADMIN BROADCAST ================= #

@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return

    await state.set_state(AdminBroadcastState.entering_message)
    text = (
        "📢 <b>Barcha foydalanuvchilarga xabarnoma yuborish (Broadcast):</b>\n\n"
        "Yubormoqchi bo'lgan xabaringizni (matn yoki rasm + matn) shu chatga yuboring.\n"
        "<i>Bekor qilish uchun /cancel yoki pastdagi tugmani bosing.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_back_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_back_keyboard())
    await callback.answer()


@router.message(AdminBroadcastState.entering_message)
async def process_admin_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Broadcast bekor qilindi.", reply_markup=get_admin_main_keyboard())
        return

    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session=session, segment="all")

    await state.clear()
    status_msg = await message.answer(f"⏳ Xabarnoma yuborilmoqda... Jami qabul qiluvchilar: {len(recipients)} ta")

    success_count = 0
    fail_count = 0

    for uid in recipients:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success_count += 1
            await asyncio.sleep(0.04) # ~25 msgs/sec safe rate limit
        except Exception:
            fail_count += 1

    await status_msg.edit_text(
        f"✅ <b>Xabarnoma yuborish yakunlandi!</b>\n\n"
        f"• Muvaffaqiyatli: <b>{success_count} ta</b>\n"
        f"• Yuborilmadi (bloklagan): <b>{fail_count} ta</b>",
        reply_markup=get_admin_main_keyboard()
    )


# ================= ADMIN PRICES ================= #

@router.callback_query(F.data == "admin:prices")
async def cb_admin_prices(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        if not await is_admin_user(user_id, session):
            await callback.answer("Ruxsat yo'q!", show_alert=True)
            return
        pricing = await queries.get_pricing(session)

    text = (
        "💵 <b>Narxlar va Marja sozlamalari:</b>\n\n"
        f"• 1 dona Stars tannarxi: <b>{pricing.star_unit_price_uzs:,.0f} so'm</b>\n"
        f"• Marja (ustama foiz): <b>{pricing.margin_percent}%</b>\n"
        f"• 1 TON kursi: <b>{pricing.ton_rate_uzs:,.0f} so'm</b>\n\n"
        "Narxlarni batafsil va qulay o'zgartirish uchun Web App admin panelidan foydalaning:"
    )

    admin_url = config.get_admin_app_url() if hasattr(config, "get_admin_app_url") else config.ADMIN_APP_URL
    rows = []
    if admin_url and admin_url.startswith("https://"):
        rows.append([
            InlineKeyboardButton(text="⚙️ Narxlarni o'zgartirish (Web App)", web_app=WebAppInfo(url=f"{admin_url}"))
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="⚙️ Narxlarni o'zgartirish (Web App)", url=admin_url or "https://t.me")
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Admin panelga qaytish", callback_data="admin:menu")
    ])

    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()
