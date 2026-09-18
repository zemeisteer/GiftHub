import json
import logging
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database.db import AsyncSessionLocal
from database import queries
from data import config
from app.state.user_states import StarsPurchaseState, PremiumPurchaseState, GiftPurchaseState, ServicePurchaseState
from app.keyboards.shop_keyboards import (
    get_shop_main_menu,
    get_stars_keyboard,
    get_recipient_keyboard,
    get_user_request_keyboard,
    get_confirm_purchase_keyboard,
    get_premium_keyboard,
    get_gifts_keyboard,
    get_insufficient_balance_keyboard,
    get_back_to_main_keyboard,
    get_services_keyboard,
    get_service_detail_keyboard,
    get_service_purchase_confirm_keyboard
)
from app.services.fragment import pricing_engine

router = Router()
logger = logging.getLogger(__name__)

# ================= STARS FLOW ================= #

@router.callback_query(F.data == "shop:stars")
async def cb_shop_stars(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        packages_stars = [50, 100, 250, 500, 1000, 2500]
        packages = []
        for st in packages_stars:
            calc = queries.calculate_stars_price(st, pricing)
            p_uzs = float(calc.get("total_price_uzs") or calc.get("final_price_uzs") or 0.0)
            c_uzs = float(calc.get("cost_total_uzs") or calc.get("base_cost_uzs") or 0.0)
            packages.append({
                "stars": st,
                "price_uzs": p_uzs,
                "cost_uzs": c_uzs
            })

    text = (
        "⭐ <b>Telegram Stars xaridi</b>\n\n"
        "Stars orqali Telegramdagi botlar, Mini App'lar va kanallardagi pullik kontentlar uchun to'lov qilishingiz mumkin.\n\n"
        "Kerakli miqdorni tanlang yoki o'zingiz xohlagan sonni kiriting:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_stars_keyboard(packages))
    except Exception:
        await callback.message.answer(text, reply_markup=get_stars_keyboard(packages))
    await callback.answer()


@router.callback_query(F.data.startswith("stars:pkg:"))
async def cb_stars_package(callback: CallbackQuery, state: FSMContext):
    stars_amount = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        calc = queries.calculate_stars_price(stars_amount, pricing)

    price_val = float(calc.get("total_price_uzs") or calc.get("final_price_uzs") or 0.0)
    cost_val = float(calc.get("cost_total_uzs") or calc.get("base_cost_uzs") or 0.0)

    await state.update_data(
        product_type="stars",
        item_title=f"{stars_amount} Telegram Stars",
        amount=stars_amount,
        total_price=price_val,
        cost_price=cost_val
    )

    my_username = callback.from_user.username
    text = (
        f"⭐ <b>{stars_amount} dona Stars</b> tanlandi.\n"
        f"Narxi: <b>{price_val:,.0f} so'm</b>\n\n"
        "Stars qaysi profilga yuborilishi kerak?"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_recipient_keyboard(my_username))
    except Exception:
        await callback.message.answer(text, reply_markup=get_recipient_keyboard(my_username))
    await callback.answer()


@router.callback_query(F.data == "stars:custom")
async def cb_stars_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StarsPurchaseState.entering_amount)
    text = (
        "✍️ <b>Ixtiyoriy miqdorda Stars kiritish:</b>\n\n"
        "Qancha Stars sotib olmoqchisiz? (Minimal: <b>50</b>, maksimal: <b>50 000</b>)\n\n"
        "<i>Faqat raqam yuboring, masalan: 150</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()


@router.message(StarsPurchaseState.entering_amount)
async def process_stars_custom_amount(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("⚠️ Iltimos, faqat musbat butun son kiriting (masalan: 120):")
        return

    amount = int(txt)
    if amount < 50 or amount > 50000:
        await message.answer("⚠️ Stars miqdori 50 dan 50 000 gacha bo'lishi kerak. Qaytadan kiriting:")
        return

    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        calc = queries.calculate_stars_price(amount, pricing)

    price_val = float(calc.get("total_price_uzs") or calc.get("final_price_uzs") or 0.0)
    cost_val = float(calc.get("cost_total_uzs") or calc.get("base_cost_uzs") or 0.0)

    await state.update_data(
        product_type="stars",
        item_title=f"{amount} Telegram Stars",
        amount=amount,
        total_price=price_val,
        cost_price=cost_val
    )

    my_username = message.from_user.username
    text = (
        f"⭐ <b>{amount} dona Stars</b> tanlandi.\n"
        f"Narxi: <b>{price_val:,.0f} so'm</b>\n\n"
        "Stars qaysi profilga yuborilishi kerak?"
    )
    await message.answer(text, reply_markup=get_recipient_keyboard(my_username))


# ================= PREMIUM FLOW ================= #

@router.callback_query(F.data == "shop:premium")
async def cb_shop_premium(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        prices = {}
        try:
            if pricing.premium_prices_json:
                prices = json.loads(pricing.premium_prices_json)
        except Exception:
            prices = {"3": 142000, "6": 210000, "12": 380000}

    text = (
        "💎 <b>Telegram Premium obunasi</b>\n\n"
        "Premium afzalliklari: 4 GB yuklash, tezkor tezlik, ovozli xabarlarni matnga aylantirish, "
        "eksklyuziv stikerlar, reaksiya va nishonlar.\n\n"
        "Kerakli obuna muddatini tanlang:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_premium_keyboard(prices))
    except Exception:
        await callback.message.answer(text, reply_markup=get_premium_keyboard(prices))
    await callback.answer()


@router.callback_query(F.data.startswith("premium:pkg:"))
async def cb_premium_package(callback: CallbackQuery, state: FSMContext):
    months = callback.data.split(":")[2]
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        prices = {}
        try:
            if pricing.premium_prices_json:
                prices = json.loads(pricing.premium_prices_json)
        except Exception:
            prices = {"3": 142000, "6": 210000, "12": 380000}
        price = float(prices.get(months, 145000))

    base_costs = pricing_engine.get_premium_base_costs()
    cost = base_costs.get(months, price * 0.9)

    await state.update_data(
        product_type="premium",
        item_title=f"Telegram Premium ({months} oylik)",
        amount=int(months),
        total_price=price,
        cost_price=cost
    )

    my_username = callback.from_user.username
    text = (
        f"💎 <b>Telegram Premium ({months} oylik)</b> tanlandi.\n"
        f"Narxi: <b>{price:,.0f} so'm</b>\n\n"
        "Obuna qaysi profilga faollashtirilishi kerak?"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_recipient_keyboard(my_username))
    except Exception:
        await callback.message.answer(text, reply_markup=get_recipient_keyboard(my_username))
    await callback.answer()


# ================= GIFTS FLOW ================= #

@router.callback_query(F.data == "shop:gifts")
async def cb_shop_gifts(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        gifts = []
        try:
            if pricing.gifts_json:
                gifts = json.loads(pricing.gifts_json)
        except Exception:
            gifts = []
        if not gifts:
            gifts = [
                {"id": "bear", "name": "Teddy Bear", "price_uzs": 64000, "cost_uzs": 50000, "icon": "🧸", "type": "3d"},
                {"id": "heart", "name": "Neon Heart", "price_uzs": 85000, "cost_uzs": 68000, "icon": "💖", "type": "3d"},
                {"id": "rocket", "name": "Cosmo Rocket", "price_uzs": 120000, "cost_uzs": 95000, "icon": "🚀", "type": "3d"},
                {"id": "star", "name": "Cosmic Star", "price_uzs": 60000, "cost_uzs": 45000, "icon": "⭐", "type": "classic"},
                {"id": "ring", "name": "Diamond Ring", "price_uzs": 165000, "cost_uzs": 130000, "icon": "💍", "type": "3d"},
                {"id": "trophy", "name": "Gold Trophy", "price_uzs": 195000, "cost_uzs": 155000, "icon": "🏆", "type": "vip"},
                {"id": "yacht", "name": "Luxury Yacht", "price_uzs": 270000, "cost_uzs": 220000, "icon": "🛥️", "type": "vip"},
                {"id": "crown", "name": "Ruby Crown", "price_uzs": 225000, "cost_uzs": 180000, "icon": "👑", "type": "vip"},
                {"id": "medal", "name": "Star Medal", "price_uzs": 95000, "cost_uzs": 75000, "icon": "🎖️", "type": "classic"},
                {"id": "hat", "name": "Magic Hat", "price_uzs": 78000, "cost_uzs": 60000, "icon": "🎩", "type": "classic"},
                {"id": "eagle", "name": "Flying Eagle", "price_uzs": 110000, "cost_uzs": 88000, "icon": "🦅", "type": "3d"},
                {"id": "lion", "name": "Golden Lion", "price_uzs": 175000, "cost_uzs": 140000, "icon": "🦁", "type": "vip"}
            ]

    text = (
        "🎁 <b>Raqamli Sovg'alar (Telegram Gifts)</b>\n\n"
        "Do'stlaringiz va yaqinlaringiz profiliga Telegram orqali chiroyli va qimmatbaho sovg'alar yuboring!\n\n"
        "Kerakli sovg'ani tanlang:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_gifts_keyboard(gifts))
    except Exception:
        await callback.message.answer(text, reply_markup=get_gifts_keyboard(gifts))
    await callback.answer()


@router.callback_query(F.data.startswith("gift:pkg:"))
async def cb_gift_package(callback: CallbackQuery, state: FSMContext):
    gift_id = callback.data.split(":")[2]
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        gifts = []
        try:
            if pricing.gifts_json:
                gifts = json.loads(pricing.gifts_json)
        except Exception:
            gifts = []
        matched = next((g for g in gifts if g.get("id") == gift_id), None)

    if not matched:
        matched = {"id": gift_id, "name": "Sovg'a", "price_uzs": 75000, "cost_uzs": 65000, "icon": "🎁"}

    price = float(matched.get("price_uzs", 75000))
    cost = float(matched.get("cost_uzs", 65000))
    name = f"{matched.get('icon', '🎁')} {matched.get('name', 'Sovg\'a')}"

    await state.update_data(
        product_type="gift",
        item_title=name,
        amount=1,
        total_price=price,
        cost_price=cost
    )

    my_username = callback.from_user.username
    text = (
        f"🎁 <b>{name}</b> tanlandi.\n"
        f"Narxi: <b>{price:,.0f} so'm</b>\n\n"
        "Sovg'a qaysi profilga yuborilishi kerak?"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_recipient_keyboard(my_username))
    except Exception:
        await callback.message.answer(text, reply_markup=get_recipient_keyboard(my_username))
    await callback.answer()


# ================= RECIPIENT & CONFIRMATION ================= #

@router.callback_query(F.data.startswith("recipient:self:"))
async def cb_recipient_self(callback: CallbackQuery, state: FSMContext):
    clean_user = callback.data.split(":")[2]
    data = await state.get_data()
    if not data or "total_price" not in data:
        await callback.answer("⚠️ Ma'lumot eskirgan, iltimos qaytadan tanlang.", show_alert=True)
        return

    await state.update_data(recipient=clean_user)
    await show_order_confirmation(callback, state, clean_user)
    await callback.answer()


@router.callback_query(F.data == "recipient:other")
async def cb_recipient_other(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StarsPurchaseState.entering_recipient)
    text = (
        "👥 <b>Qabul qiluvchi do'stingizni tanlang:</b>\n\n"
        "Quyidagi <b>«👥 Do'stni tanlash»</b> tugmasini bosing — Telegram kontaktlaringiz va chatlaringiz ro'yxati chiqadi, "
        "o'sha yerdan do'stingizni tanlashingiz mumkin.\n\n"
        "<i>(Username yoki ID yozish shart emas! Agar xohlasangiz, @username tarzida xabar yuborishingiz ham mumkin)</i>"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(text, reply_markup=get_user_request_keyboard())
    await callback.answer()


@router.message(StarsPurchaseState.entering_recipient, F.users_shared)
async def process_recipient_users_shared(message: Message, state: FSMContext):
    users = message.users_shared.users
    if not users:
        await message.answer("⚠️ Hech kim tanlanmadi. Iltimos, qaytadan urinib ko'ring:")
        return

    shared = users[0]
    username = (shared.username or "").lstrip("@")
    first_name = shared.first_name or ""
    last_name = shared.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    recipient = username if username else str(shared.user_id)

    await state.update_data(
        recipient=recipient,
        recipient_name=full_name,
        recipient_id=shared.user_id
    )

    try:
        rm = await message.answer("✅ Qabul qiluvchi tanlandi!", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass

    await show_order_confirmation(message, state, recipient)


@router.message(StarsPurchaseState.entering_recipient, F.user_shared)
async def process_recipient_single_shared(message: Message, state: FSMContext):
    user_id = message.user_shared.user_id
    recipient = str(user_id)
    await state.update_data(recipient=recipient, recipient_id=user_id)
    try:
        rm = await message.answer("✅ Qabul qiluvchi tanlandi!", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass
    await show_order_confirmation(message, state, recipient)


@router.message(StarsPurchaseState.entering_recipient, F.text.in_(["❌ Bekor qilish", "Bekor qilish", "/cancel"]))
async def cancel_recipient_selection(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Foydalanuvchi"
    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        from app.handlers.users.start import check_admin_status, build_main_menu_text
        is_admin = await check_admin_status(user_id, session)
        services = await queries.list_custom_services(session, active_only=True)

    try:
        rm = await message.answer("❌ Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass

    await message.answer(
        text=build_main_menu_text(first_name, balance, user_id, services_count=len(services), services=services),
        reply_markup=get_shop_main_menu(is_admin=is_admin, services_count=len(services), services=services)
    )


@router.message(StarsPurchaseState.entering_recipient, F.text)
async def process_recipient_text(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if raw.lower() in ["❌ bekor qilish", "bekor qilish", "/cancel"]:
        return await cancel_recipient_selection(message, state)

    txt = raw.lstrip("@")
    if len(txt) < 3:
        await message.answer(
            "⚠️ Yaroqsiz username! Kamida 3 ta belgidan iborat bo'lishi kerak. Qaytadan kiriting yoki «👥 Do'stni tanlash» tugmasidan foydalaning:",
            reply_markup=get_user_request_keyboard()
        )
        return

    await state.update_data(recipient=txt, recipient_name="", recipient_id=None)
    try:
        rm = await message.answer("⏳ Qabul qiluvchi saqlandi...", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass
    await show_order_confirmation(message, state, txt)


async def show_order_confirmation(target_event, state: FSMContext, recipient: str):
    data = await state.get_data()
    item_title = data.get("item_title", "Mahsulot")
    total_price = data.get("total_price", 0.0)
    recip_name = data.get("recipient_name")

    if recipient.isdigit():
        recip_display = f"{recip_name} (ID: {recipient})" if recip_name else f"ID: {recipient}"
    else:
        recip_display = f"@{recipient.lstrip('@')}"
        if recip_name:
            recip_display += f" ({recip_name})"

    user_id = target_event.from_user.id
    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        current_balance = user.balance if user else 0.0

    text = (
        "🛒 <b>Buyurtmani tasdiqlash</b>\n\n"
        f"📦 Mahsulot: <b>{item_title}</b>\n"
        f"👤 Qabul qiluvchi: <b>{recip_display}</b>\n"
        f"💰 Xarid summasi: <b>{total_price:,.0f} so'm</b>\n"
        "────────────────────\n"
        f"💳 Sizning balansingiz: <b>{current_balance:,.0f} so'm</b>\n"
    )

    if current_balance < total_price:
        diff = total_price - current_balance
        text += (
            f"\n⚠️ <b>Balansingizda mablag' yetarli emas!</b>\n"
            f"Xaridni amalga oshirish uchun yana <b>{diff:,.0f} so'm</b> kerak.\n"
            "Iltimos, avval hisobingizni to'ldiring."
        )
        if isinstance(target_event, CallbackQuery):
            await target_event.message.edit_text(text, reply_markup=get_insufficient_balance_keyboard(diff))
        else:
            await target_event.answer(text, reply_markup=get_insufficient_balance_keyboard(diff))
    else:
        text += "\nDavom etish uchun quyidagi <b>«✅ Xaridni tasdiqlash»</b> tugmasini bosing:"
        confirm_key = f"{data.get('product_type')}:{data.get('amount')}"
        if isinstance(target_event, CallbackQuery):
            await target_event.message.edit_text(text, reply_markup=get_confirm_purchase_keyboard(confirm_key))
        else:
            await target_event.answer(text, reply_markup=get_confirm_purchase_keyboard(confirm_key))


@router.callback_query(F.data.startswith("buy:confirm:"))
async def cb_execute_purchase(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data or "total_price" not in data:
        await callback.answer("⚠️ Ma'lumot eskirgan, iltimos boshidan tanlang.", show_alert=True)
        return

    user_id = callback.from_user.id
    product_type = data.get("product_type", "stars")
    item_title = data.get("item_title", "Mahsulot")
    amount = data.get("amount", 1)
    total_price = float(data.get("total_price", 0.0))
    cost_price = float(data.get("cost_price", 0.0))
    recipient = data.get("recipient", callback.from_user.username or "")
    recip_name = data.get("recipient_name")

    if recipient.isdigit():
        recip_display = f"{recip_name} (ID: {recipient})" if recip_name else f"ID: {recipient}"
    else:
        recip_display = f"@{recipient.lstrip('@')}"
        if recip_name:
            recip_display += f" ({recip_name})"

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        if not user or user.balance < total_price:
            await callback.answer("❌ Balansingizda mablag' yetarli emas!", show_alert=True)
            return

        try:
            order, bonus, referrer = await queries.create_order(
                session=session,
                user_id=user_id,
                product_type=product_type,
                item_title=item_title,
                amount=amount,
                total_price=total_price,
                cost_price=cost_price,
                recipient_username=recipient
            )
            new_balance = user.balance
        except Exception as e:
            logger.error(f"Xarid yaratishda xatolik: {e}")
            await callback.answer("❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.", show_alert=True)
            return

    await state.clear()

    # Trigger Fragment auto-fulfillment in background for Stars, Premium, Gifts
    if product_type in ["stars", "premium", "gift"]:
        import asyncio
        from app.services.fragment import fragment_client
        asyncio.create_task(
            fragment_client.fulfill_order(order_id=order.id, bot=callback.bot)
        )

    success_text = (
        "🎉 <b>Xaridingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"🔖 Buyurtma raqami: <code>{order.order_code}</code>\n"
        f"📦 Mahsulot: <b>{item_title}</b>\n"
        f"👤 Qabul qiluvchi: <b>{recip_display}</b>\n"
        f"💵 To'langan summa: <b>{total_price:,.0f} so'm</b>\n"
        f"💳 Qolgan balansingiz: <b>{new_balance:,.0f} so'm</b>\n\n"
        "⚡ <i>Telegram Stars / Premium tez orada profilingizga yetkazib beriladi!</i>"
    )

    try:
        await callback.message.edit_text(success_text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(success_text, reply_markup=get_back_to_main_keyboard())
    await callback.answer("✅ Xarid muvaffaqiyatli amalga oshirildi!")


# ================= CUSTOM SERVICES FLOW ================= #

@router.callback_query(F.data == "shop:services")
async def cb_shop_services(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        services = await queries.list_custom_services(session, active_only=True)

    if not services:
        text = (
            "⚡ <b>Yangi va Qo'shimcha Xizmatlar</b>\n\n"
            "Hozirda faol qo'shimcha xizmatlar mavjud emas.\n"
            "Tez orada yangi qulay xizmatlar qo'shiladi!"
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
        except Exception:
            await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
        await callback.answer()
        return

    text = (
        "⚡ <b>Yangi va Qo'shimcha Xizmatlar</b>\n\n"
        "Quyidagi xizmatlardan birini tanlab, to'liq ma'lumot olishingiz va qulay xarid qilishingiz mumkin:"
    )
    kb = get_services_keyboard(services)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("srv:view:"))
async def cb_service_view(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    service_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        service = await queries.get_custom_service(session, service_id)
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0

    if not service or not service.is_active:
        await callback.answer("⚠️ Bu xizmat hozirda mavjud emas!", show_alert=True)
        return

    can_afford = balance >= service.price_uzs
    balance_status = f"✅ Mablag' yetarli ({balance:,.0f} so'm)" if can_afford else f"⚠️ Mablag' yetarli emas (Balansingiz: {balance:,.0f} so'm)"

    desc = service.description or "Batafsil ma'lumot berilmagan."
    text = (
        f"{service.icon} <b>{service.name}</b>\n\n"
        f"🏷 <b>Kategoriya:</b> {service.category}\n"
        f"💵 <b>Narxi:</b> <b>{service.price_uzs:,.0f} so'm</b>\n"
        f"💰 <b>Balansingiz:</b> {balance_status}\n\n"
        f"📝 <b>Xizmat haqida:</b>\n{desc}\n\n"
        "Xizmatni xarid qilish uchun quyidagi tugmani bosing:"
    )
    kb = get_service_detail_keyboard(service_id=service.id, can_afford=can_afford)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("srv:buy:"))
async def cb_service_buy_start(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        service = await queries.get_custom_service(session, service_id)
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0

    if not service or not service.is_active:
        await callback.answer("⚠️ Bu xizmat faol emas!", show_alert=True)
        return

    if balance < service.price_uzs:
        diff = service.price_uzs - balance
        text = (
            f"❌ <b>Balansingizda yetarli mablag' mavjud emas!</b>\n\n"
            f"Xizmat: <b>{service.icon} {service.name}</b>\n"
            f"Narxi: <b>{service.price_uzs:,.0f} so'm</b>\n"
            f"Sizning balansingiz: <b>{balance:,.0f} so'm</b>\n"
            f"Yetishmayotgan summa: <b>{diff:,.0f} so'm</b>\n\n"
            "Iltimos, avval hamyoningizni to'ldiring:"
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_insufficient_balance_keyboard(diff))
        except Exception:
            await callback.message.answer(text, reply_markup=get_insufficient_balance_keyboard(diff))
        await callback.answer()
        return

    await state.set_state(ServicePurchaseState.entering_details)
    await state.update_data(
        service_id=service.id,
        service_name=service.name,
        service_icon=service.icon,
        price_uzs=service.price_uzs,
        cost_uzs=service.cost_uzs,
        category=service.category
    )

    text = (
        f"{service.icon} <b>{service.name} xaridi</b>\n\n"
        f"💵 Narxi: <b>{service.price_uzs:,.0f} so'm</b>\n\n"
        "✍️ <b>Xizmatni ulash / faollashtirish uchun ma'lumotingizni kiriting:</b>\n"
        "<i>(Masalan: Telegram @username, profilingiz havolasi, emailingiz yoki telefon raqamingiz)</i>\n\n"
        "Bekor qilish uchun quyidagi tugmani bosing:"
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=f"srv:view:{service_id}")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=cancel_kb)
    except Exception:
        await callback.message.answer(text, reply_markup=cancel_kb)
    await callback.answer()


@router.message(ServicePurchaseState.entering_details, F.text)
async def msg_service_details(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if raw.lower() in ["/cancel", "bekor qilish", "❌ bekor qilish"]:
        data = await state.get_data()
        service_id = data.get("service_id")
        await state.clear()
        if service_id:
            class DummyCallback:
                def __init__(self, msg, sid):
                    self.message = msg
                    self.from_user = msg.from_user
                    self.data = f"srv:view:{sid}"
                    self.bot = msg.bot
                async def answer(self, *args, **kwargs):
                    pass
            return await cb_service_view(DummyCallback(message, service_id), state)
        from app.handlers.users.start import cmd_start
        return await cmd_start(message, None, state)

    if len(raw) < 2:
        await message.answer("⚠️ Iltimos, hisob yoki @username ma'lumotini to'g'ri kiriting:")
        return

    data = await state.get_data()
    service_id = data.get("service_id")
    service_name = data.get("service_name")
    service_icon = data.get("service_icon", "⚡")
    price_uzs = float(data.get("price_uzs", 0.0))

    await state.update_data(recipient_detail=raw)
    await state.set_state(ServicePurchaseState.confirming)

    text = (
        "⚡ <b>Xaridni tasdiqlang</b>\n\n"
        f"📦 Xizmat: <b>{service_icon} {service_name}</b>\n"
        f"💵 Narxi: <b>{price_uzs:,.0f} so'm</b>\n"
        f"👤 Qabul qiluvchi / Hisob: <code>{raw}</code>\n"
        f"💰 Balansingizdan yechiladi: <b>{price_uzs:,.0f} so'm</b>\n\n"
        "Xaridni tasdiqlaysizmi?"
    )
    kb = get_service_purchase_confirm_keyboard(service_id=service_id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(ServicePurchaseState.confirming, F.data.startswith("srv:confirm:"))
async def cb_service_purchase_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service_id = data.get("service_id")
    service_name = data.get("service_name")
    service_icon = data.get("service_icon", "⚡")
    price_uzs = float(data.get("price_uzs", 0.0))
    cost_uzs = float(data.get("cost_uzs", 0.0))
    recipient_detail = data.get("recipient_detail", "")

    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        if not user or user.balance < price_uzs:
            await callback.answer("❌ Balansingizda mablag' yetarli emas!", show_alert=True)
            return

        try:
            order, bonus, referrer = await queries.create_order(
                session=session,
                user_id=user_id,
                product_type="service",
                item_title=f"{service_icon} {service_name}",
                amount=1,
                total_price=price_uzs,
                cost_price=cost_uzs,
                recipient_username=recipient_detail,
                status="pending"
            )
            new_balance = user.balance
        except Exception as e:
            logger.error(f"Xizmat xaridi yaratishda xatolik: {e}")
            await callback.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.", show_alert=True)
            return

    await state.clear()

    success_text = (
        "🎉 <b>Xaridingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"🔖 Buyurtma kodi: <code>{order.order_code}</code>\n"
        f"📦 Xizmat: <b>{service_icon} {service_name}</b>\n"
        f"👤 Qabul qiluvchi / Hisob: <code>{recipient_detail}</code>\n"
        f"💵 To'langan summa: <b>{price_uzs:,.0f} so'm</b>\n"
        f"💳 Qolgan balansingiz: <b>{new_balance:,.0f} so'm</b>\n\n"
        "⏳ <b>Eslatma:</b> Taklif havolasi (link) eskirib, kuyib ketishining oldini olish uchun — eng yangi havola admin tomonidan sizga tez orada ushbu bot orqali yuboriladi!"
    )
    try:
        await callback.message.edit_text(success_text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(success_text, reply_markup=get_back_to_main_keyboard())
    await callback.answer("✅ Xarid muvaffaqiyatli amalga oshirildi!")

    # Adminlarga yangi buyurtma haqida xabarnoma yuborish
    admin_notify_text = (
        "⚡ <b>Yangi xizmat buyurtmasi!</b>\n\n"
        f"🔖 Buyurtma: <code>{order.order_code}</code>\n"
        f"📦 Xizmat: <b>{service_icon} {service_name}</b>\n"
        f"💵 Narxi: <b>{price_uzs:,.0f} so'm</b> (Tannarxi: {cost_uzs:,.0f} so'm)\n"
        f"👤 Xaridor: <a href='tg://user?id={user_id}'>{callback.from_user.full_name}</a> (<code>{user_id}</code>)\n"
        f"📝 Qabul qiluvchi ma'lumoti: <code>{recipient_detail}</code>\n"
        f"📊 Holati: ⏳ <b>Kutilmoqda (pending)</b>\n\n"
        "💡 <i>Havolani mijozga yuborish yoki bekor qilish uchun quyidagi tugmani bosing:</i>"
    )
    admin_action_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔗 Havola (Link) yuborish", callback_data=f"adm_srv:send:{order.id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"adm_srv:cancel:{order.id}")
        ]
    ])
    for adm in config.ADMINS:
        try:
            await callback.bot.send_message(chat_id=int(adm), text=admin_notify_text, reply_markup=admin_action_kb)
        except Exception as e:
            logger.warning(f"Adminga xizmat buyurtmasi xabarini yuborishda xatolik ({adm}): {e}")

