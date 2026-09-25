import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.keyboards.shop_keyboards import get_orders_keyboard
from app.services.orders.service import order_service
from app.services.pricing.service import pricing_service
from database import queries
from database.db import AsyncSessionLocal

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
        kb = get_orders_keyboard()
    else:
        text = "📋 <b>Sizning oxirgi buyurtmalaringiz:</b>\n\n"
        buttons = []
        for ord_item in orders[:5]:
            if ord_item.status in ["done", "completed"]:
                st_icon = "✅ Bajarildi"
            elif ord_item.status in ["pending", "processing"]:
                st_icon = "⏳ Jarayonda"
            else:
                st_icon = "❌ Bekor qilingan"

            date_str = ord_item.created_at.strftime("%d.%m.%Y %H:%M")
            rec = f"@{ord_item.recipient_username}" if ord_item.recipient_username else "O'zim"
            link_info = ""
            if ord_item.product_type == "service" and ord_item.fragment_payload and ord_item.status in ["done", "completed"]:
                link_info = f"\n   🔗 <b>Havola:</b> {ord_item.fragment_payload}\n   ⚠️ <i>24 soat ichida ulaning</i>"

            text += (
                f"🔖 <b>{ord_item.order_code}</b> — {ord_item.item_title}\n"
                f"   Summa: <b>{ord_item.total_price:,.0f} UZS</b> | {st_icon}\n"
                f"   Qabul qiluvchi: {rec} ({date_str}){link_info}\n\n"
            )

            # Add quick actions for each order
            buttons.append([
                InlineKeyboardButton(
                    text=f"🧾 Chek #{ord_item.order_code}",
                    callback_data=f"order:receipt:{ord_item.order_code}"
                ),
                InlineKeyboardButton(
                    text="🔁 Qayta olish",
                    callback_data=f"order:buyagain:{ord_item.order_code}"
                )
            ])

        buttons.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="orders:history")])
        buttons.append([InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="menu:main")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.debug(f"Could not edit orders message: {e}")
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("order:receipt:"))
async def cb_order_receipt(callback: CallbackQuery):
    order_code = callback.data.split("order:receipt:")[1]
    async with AsyncSessionLocal() as session:
        order = await order_service.get_order_by_id_or_code(session, order_code)
        if not order or order.user_id != callback.from_user.id:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return

        date_str = order.created_at.strftime("%d.%m.%Y %H:%M") if order.created_at else "-"
        currency = getattr(order, "currency", "UZS") or "UZS"
        rec = f"@{order.recipient_username}" if order.recipient_username else "O'zim"
        unit_price = float(order.unit_price or 0)
        total_price = float(order.total_price or 0)

        receipt_text = (
            f"🧾 <b>RASMIY TO'LOV CHEKI #{order.order_code}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Mahsulot:</b> {order.item_title}\n"
            f"🔢 <b>Miqdori:</b> {order.amount} dona\n"
            f"👤 <b>Qabul qiluvchi:</b> {rec}\n"
            f"💵 <b>Dona narxi:</b> {unit_price:,.0f} {currency}\n"
            f"💰 <b>Jami to'langan:</b> <b>{total_price:,.0f} {currency}</b>\n"
            f"💳 <b>To'lov usuli:</b> {(order.payment_method or 'balance').upper()}\n"
            f"🚦 <b>Holat:</b> {order.status.upper()}\n"
            f"📅 <b>Sana:</b> {date_str}\n"
        )
        if order.fragment_tx_hash:
            receipt_text += f"🔗 <b>Fragment TX:</b> <code>{order.fragment_tx_hash}</code>\n"
        receipt_text += "━━━━━━━━━━━━━━━━━━━━\n<i>GiftHub kafolatlangan raqamli xizmati</i>"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Ushbu mahsulotni qayta sotib olish",
                    callback_data=f"order:buyagain:{order.order_code}"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Buyurtmalar ro'yxatiga qaytish", callback_data="orders:history")
            ]
        ])

        try:
            await callback.message.edit_text(receipt_text, reply_markup=kb)
        except Exception as e:
            logger.debug(f"Could not edit receipt message: {e}")
            await callback.message.answer(receipt_text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("order:buyagain:"))
async def cb_order_buy_again(callback: CallbackQuery):
    order_code = callback.data.split("order:buyagain:")[1]
    async with AsyncSessionLocal() as session:
        order = await order_service.get_order_by_id_or_code(session, order_code)
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return

        # Calculate current authoritative live price
        live_price_info = await pricing_service.get_authoritative_price(
            session=session,
            product_type=order.product_type,
            amount=order.amount,
            item_title=order.item_title
        )
        current_price = float(live_price_info["total_price_decimal"])
        currency = "UZS"
        rec = f"@{order.recipient_username}" if order.recipient_username else "O'zim"

        prompt_text = (
            f"🔁 <b>Qayta xarid qilish</b>\n\n"
            f"📦 <b>Mahsulot:</b> {order.item_title}\n"
            f"👤 <b>Qabul qiluvchi:</b> {rec}\n"
            f"💰 <b>Joriy narx:</b> <b>{current_price:,.0f} {currency}</b>\n\n"
            f"<i>💡 Eslatma: Narx joriy Fragment kursi va sozlamalari asosida qayta hisoblandi. "
            f"Tarixiy narx: {float(order.total_price):,.0f} {currency}</i>\n\n"
            f"Xaridni tasdiqlaysizmi?"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Xaridni tasdiqlash ({current_price:,.0f} {currency})",
                    callback_data=f"order:confirm_buyagain:{order.order_code}"
                )
            ],
            [
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="orders:history")
            ]
        ])

        try:
            await callback.message.edit_text(prompt_text, reply_markup=kb)
        except Exception as e:
            logger.debug(f"Could not edit buyagain prompt: {e}")
            await callback.message.answer(prompt_text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("order:confirm_buyagain:"))
async def cb_order_confirm_buy_again(callback: CallbackQuery):
    order_code = callback.data.split("order:confirm_buyagain:")[1]
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        order = await order_service.get_order_by_id_or_code(session, order_code)
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return

        user = await queries.get_user(session, user_id=user_id)
        if not user:
            await callback.answer("Foydalanuvchi topilmadi!", show_alert=True)
            return

        live_price_info = await pricing_service.get_authoritative_price(
            session=session,
            product_type=order.product_type,
            amount=order.amount,
            item_title=order.item_title
        )
        total_price = live_price_info["total_price_decimal"]

        # Check user balance
        if user.balance < total_price:
            diff = total_price - user.balance
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Hamyonni to'ldirish", callback_data="wallet:topup")],
                [InlineKeyboardButton(text="🔙 Buyurtmalar", callback_data="orders:history")]
            ])
            await callback.message.answer(
                f"❌ Balansingizda yetarli mablag' mavjud emas.\n"
                f"Sizning balansingiz: <b>{user.balance:,.0f} UZS</b>\n"
                f"Yetishmayotgan summa: <b>{diff:,.0f} UZS</b>",
                reply_markup=kb
            )
            await callback.answer()
            return

        # Create order and atomically debit balance via WalletService
        new_order, _, _ = await order_service.create_order(
            session=session,
            user_id=user_id,
            product_type=order.product_type,
            item_title=order.item_title,
            amount=order.amount,
            recipient_username=order.recipient_username,
            payment_method="balance"
        )

        from app.services.wallet.service import wallet_service
        await wallet_service.debit_balance(
            session=session,
            user_id=user_id,
            amount=total_price,
            tx_type="purchase",
            reference_type="order",
            reference_id=new_order.order_code,
            note=f"Qayta xarid: #{new_order.order_code} ({new_order.item_title})"
        )

        await order_service.transition_order_status(
            session=session,
            order_id=new_order.id,
            new_status_raw="paid",
            actor="USER",
            reason="Hamyon balansidan to'landi"
        )
        await session.commit()

        # Trigger fulfillment asynchronously
        from app.services.fulfillment.service import fulfillment_service
        _ = await fulfillment_service.fulfill_order_automated(session, new_order.id)

        await callback.message.answer(
            f"🎉 <b>Buyurtma muvaffaqiyatli qabul qilindi!</b>\n\n"
            f"🔖 <b>Buyurtma kodi:</b> <code>{new_order.order_code}</code>\n"
            f"📦 <b>Mahsulot:</b> {new_order.item_title}\n"
            f"💰 <b>To'langan summa:</b> {float(new_order.total_price):,.0f} UZS\n\n"
            f"Yetkazib berish jarayoni boshlandi. Natija haqida bot xabar beradi.",
            reply_markup=get_orders_keyboard()
        )
    await callback.answer()
