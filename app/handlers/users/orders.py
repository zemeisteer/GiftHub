import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from database.db import AsyncSessionLocal
from database import queries
from app.keyboards.shop_keyboards import get_orders_keyboard, get_back_to_main_keyboard

router = Router()
logger = logging.getLogger(__name__)

@router.callback_query(F.data == "orders:history")
async def cb_orders_history(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        orders = await queries.list_user_orders(session=session, user_id=user_id)

    if not orders:
        text = (
            "📋 <b>Sizning buyurtmalaringiz tarixi</b>\n\n"
            "Sizda hali hech qanday xarid mavjud emas.\n"
            "Telegram Stars yoki Premium xarid qilish uchun bosh menyuga o'ting."
        )
    else:
        text = "📋 <b>Sizning oxirgi buyurtmalaringiz:</b>\n\n"
        for ord_item in orders[:8]:
            if ord_item.status == "done":
                st_icon = "✅ Bajarildi"
            elif ord_item.status == "pending":
                st_icon = "⏳ Jarayonda"
            else:
                st_icon = "❌ Bekor qilingan"

            date_str = ord_item.created_at.strftime("%d.%m.%Y %H:%M")
            rec = f"@{ord_item.recipient_username}" if ord_item.recipient_username else ""
            text += (
                f"🔖 <b>{ord_item.order_code}</b> — {ord_item.item_title}\n"
                f"   Summa: <b>{ord_item.total_price:,.0f} so'm</b> | {st_icon}\n"
                f"   Qabul qiluvchi: {rec} ({date_str})\n\n"
            )

    try:
        await callback.message.edit_text(text, reply_markup=get_orders_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_orders_keyboard())
    await callback.answer()
