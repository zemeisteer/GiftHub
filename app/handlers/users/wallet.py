import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards.shop_keyboards import (
    get_admin_receipt_approval_keyboard,
    get_back_to_main_keyboard,
    get_payment_methods_keyboard,
    get_topup_amounts_keyboard,
    get_wallet_keyboard,
)
from app.services.payments import generate_click_link, generate_payme_link
from app.state.user_states import BalanceTopupState
from data import config
from database import queries
from database.db import AsyncSessionLocal
from database.models import Transaction

router = Router()
logger = logging.getLogger(__name__)

# ================= WALLET OVERVIEW ================= #


@router.callback_query(F.data == "wallet:view")
async def cb_wallet_view(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        ref_earnings = user.referral_earnings if user else 0.0
        ref_count = user.referrals_count if user else 0

    text = (
        "💰 <b>Sizning shaxsiy hamyoningiz</b>\n\n"
        f"💳 Joriy balans: <b>{balance:,.0f} so'm</b>\n"
        f"👥 Taklif qilingan do'stlar: <b>{ref_count} ta</b>\n"
        f"🎁 Referaldan daromad: <b>{ref_earnings:,.0f} so'm</b>\n"
        "────────────────────\n"
        "Balansingizni Click, Payme yoki to'g'ridan-to'g'ri bank kartasi orqali to'ldirishingiz mumkin:"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_wallet_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_wallet_keyboard())
    await callback.answer()


# ================= TOP-UP AMOUNTS ================= #


@router.callback_query(F.data == "wallet:topup")
async def cb_wallet_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "💳 <b>Hisobni to'ldirish summasini tanlang:</b>\n\n"
        "Quyidagi tayyor summalardan birini bosing yoki o'zingiz xohlagan summani kiriting:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_topup_amounts_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_topup_amounts_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("topup:amt:"))
async def cb_topup_amount_selected(callback: CallbackQuery, state: FSMContext):
    amount = int(callback.data.split(":")[2])
    await show_payment_methods(callback, state, amount)
    await callback.answer()


@router.callback_query(F.data == "topup:custom")
async def cb_topup_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BalanceTopupState.entering_amount)
    text = (
        "✍️ <b>Ixtiyoriy to'lov summasini kiriting:</b>\n\n"
        "Minimal summa: <b>1 000 so'm</b>\n"
        "Maksimal summa: <b>10 000 000 so'm</b>\n\n"
        "<i>Faqat son yuboring, masalan: 75000</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()


@router.message(BalanceTopupState.entering_amount)
async def process_topup_custom_amount(message: Message, state: FSMContext):
    txt = (message.text or "").replace(" ", "").strip()
    if not txt.isdigit():
        await message.answer("⚠️ Iltimos, faqat musbat son kiriting (masalan: 50000):")
        return

    amount = int(txt)
    if amount < 1000 or amount > 10000000:
        await message.answer("⚠️ Summa 1 000 so'mdan 10 000 000 so'mgacha bo'lishi kerak. Qaytadan kiriting:")
        return

    await show_payment_methods(message, state, amount)


async def show_payment_methods(target_event, state: FSMContext, amount: int):
    user_id = target_event.from_user.id
    click_url = generate_click_link(user_id=user_id, amount=float(amount))
    payme_url = generate_payme_link(user_id=user_id, amount_uzs=float(amount))

    async with AsyncSessionLocal() as session:
        pay_setting = await queries.get_payment_settings(session)
        card_active = pay_setting.card_active if pay_setting else True

    text = (
        f"💳 <b>Hisobni to'ldirish: {amount:,.0f} so'm</b>\n\n"
        "To'lovni amalga oshirish uchun qulay usulni tanlang:\n\n"
        "• <b>Click / Payme:</b> Ilovaga to'g'ridan-to'g'ri o'tish orqali to'lov (avtomatik)\n"
        "• <b>Karta (P2P):</b> Karta raqamiga pul o'tkazib, chek yuborish orqali"
    )

    kb = get_payment_methods_keyboard(amount=amount, click_url=click_url, payme_url=payme_url, card_active=card_active)

    if isinstance(target_event, CallbackQuery):
        await target_event.message.edit_text(text, reply_markup=kb)
    else:
        await target_event.answer(text, reply_markup=kb)


# ================= CARD TRANSFER & RECEIPT UPLOAD ================= #


@router.callback_query(F.data.startswith("pay:card:"))
async def cb_pay_card(callback: CallbackQuery, state: FSMContext):
    amount = int(callback.data.split(":")[2])
    await state.set_state(BalanceTopupState.uploading_receipt)
    await state.update_data(topup_amount=amount)

    async with AsyncSessionLocal() as session:
        cards = await queries.list_active_payment_cards(session)

    if len(cards) <= 1:
        c = cards[0] if cards else None
        c_num = c.card_number if c else "8600 1234 5678 9012"
        c_holder = c.card_holder if c else "ANVAR S."
        c_bank = c.bank_name if c else "Bank"
        c_type = f" ({c.card_type})" if c and getattr(c, "card_type", None) else ""
        cards_block = (
            f"💳 Karta raqami: <code>{c_num}</code>\n"
            f"👤 Qabul qiluvchi: <b>{c_holder}</b>\n"
            f"🏦 Bank: <b>{c_bank}</b>{c_type}\n\n"
        )
        instruction_card = "Ko'rsatilgan kartaga"
    else:
        cards_block = "Quyidagi kartalardan biriga to'lov qilishingiz mumkin:\n\n"
        for i, c in enumerate(cards, 1):
            c_type = f" — {c.card_type}" if getattr(c, "card_type", None) else ""
            cards_block += (
                f"💳 <b>{i}-Karta: {c.bank_name}{c_type}</b>\n"
                f"Raqam: <code>{c.card_number}</code>\n"
                f"Egasi: <b>{c.card_holder}</b>\n\n"
            )
        instruction_card = "Ushbu kartalardan biriga"

    text = (
        "💳 <b>Karta orqali to'lov (P2P):</b>\n\n"
        f"To'lov summasi: <b>{amount:,.0f} so'm</b>\n\n"
        f"{cards_block}"
        "⚠️ <b>Muhim ko'rsatma:</b>\n"
        f"1. {instruction_card} aynan <b>{amount:,.0f} so'm</b> o'tkazing.\n"
        "2. To'lov amalga oshirilgach, to'lov cheki (skrinshot yoki rasmi)ni <b>shu botga rasm sifatida yuboring</b>.\n\n"
        "<i>Chek yuborilgach, adminlarimiz uni 1-5 daqiqada tasdiqlab, balansingizni to'ldirishadi.</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()


@router.message(BalanceTopupState.uploading_receipt, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data.get("topup_amount", 0)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "mavjud emas"

    photo = message.photo[-1]
    photo_file_id = photo.file_id

    async with AsyncSessionLocal() as session:
        # Create pending transaction
        tx = Transaction(
            user_id=user_id,
            amount=float(amount),
            tx_type="topup",
            method="card",
            status="pending",
            note=f"Karta orqali to'lov cheki (kutilmoqda): {amount} so'm",
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        tx_id = tx.id

    await state.clear()

    # Confirm to user
    await message.answer(
        "✅ <b>To'lov chekingiz muvaffaqiyatli qabul qilindi!</b>\n\n"
        f"To'lov summasi: <b>{amount:,.0f} so'm</b>\n"
        "Holat: ⏳ <b>Admin tekshiruvida</b>\n\n"
        "Tez orada to'lov tasdiqlanib, balansingiz to'ldiriladi va sizga xabar beriladi.",
        reply_markup=get_back_to_main_keyboard(),
    )

    # Notify admins with photo and approval buttons
    admin_caption = (
        "🔔 <b>Yangi to'lov cheki keldi!</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Foydalanuvchi: <b>{user_name}</b> ({username})\n"
        f"💰 Summa: <b>{amount:,.0f} so'm</b>\n"
        f"🧾 Tranzaksiya ID: <code>#{tx_id}</code>\n\n"
        "To'lovni tasdiqlaysizmi?"
    )

    kb = get_admin_receipt_approval_keyboard(tx_id=tx_id, user_id=user_id, amount=float(amount))
    for adm in config.ADMINS:
        try:
            await bot.send_photo(chat_id=int(adm), photo=photo_file_id, caption=admin_caption, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Adminga chek yuborishda xatolik ({adm}): {e}")


# ================= ADMIN RECEIPT APPROVAL ================= #


@router.callback_query(F.data.startswith("adm_chk:approve:"))
async def cb_admin_approve_receipt(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    tx_id = int(parts[2])
    target_user_id = int(parts[3])
    amount = float(parts[4])

    async with AsyncSessionLocal() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx:
            await callback.answer("Tranzaksiya topilmadi!", show_alert=True)
            return

        if tx.status == "success":
            await callback.answer("Bu to'lov allaqachon tasdiqlangan!", show_alert=True)
            return

        tx.status = "success"
        tx.note = f"Admin @{callback.from_user.username or callback.from_user.id} tomonidan tasdiqlandi"

        user = await queries.update_user_balance(
            session=session,
            user_id=target_user_id,
            amount=amount,
            tx_type="topup",
            method="card",
            note=f"Karta to'lovi tasdiqlandi (+{amount:,.0f} so'm)",
        )
        new_balance = user.balance if user else amount

    # Edit admin message
    new_caption = (
        f"{callback.message.caption or ''}\n\n"
        f"✅ <b>TASDIQLANDI!</b>\n"
        f"Tasdiqladi: @{callback.from_user.username or callback.from_user.first_name}"
    )
    try:
        await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception as e:
        logger.debug(f"To'lov cheki xabari sarlavhasini o'zgartirishda ogohlantirish: {e}")

    # Notify target user
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 <b>To'lovingiz muvaffaqiyatli tasdiqlandi!</b>\n\n"
                f"💰 Hisobingizga <b>+{amount:,.0f} so'm</b> qo'shildi.\n"
                f"💳 Yangi balansingiz: <b>{new_balance:,.0f} so'm</b>\n\n"
                "Endi bemalol Stars yoki Premium xarid qilishingiz mumkin!"
            ),
            reply_markup=get_back_to_main_keyboard(),
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga to'lov tasdiqlanganini bildirishda xatolik: {e}")

    await callback.answer("✅ To'lov tasdiqlandi va balans to'ldirildi!")


@router.callback_query(F.data.startswith("adm_chk:reject:"))
async def cb_admin_reject_receipt(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    tx_id = int(parts[2])
    target_user_id = int(parts[3])
    amount = float(parts[4])

    async with AsyncSessionLocal() as session:
        tx = await session.get(Transaction, tx_id)
        if tx:
            tx.status = "failed"
            tx.note = f"Admin @{callback.from_user.username or callback.from_user.id} tomonidan rad etildi"
            await session.commit()

    new_caption = (
        f"{callback.message.caption or ''}\n\n"
        f"❌ <b>RAD ETILDI!</b>\n"
        f"Rad etdi: @{callback.from_user.username or callback.from_user.first_name}"
    )
    try:
        await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception as e:
        logger.debug(f"To'lov cheki xabari sarlavhasini o'zgartirishda ogohlantirish: {e}")

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "❌ <b>Kechirasiz, to'lov chekingiz tasdiqlanmadi.</b>\n\n"
                f"Summa: <b>{amount:,.0f} so'm</b>\n\n"
                "Agar to'lovni haqiqatan amalga oshirgan bo'lsangiz, iltimos adminga murojaat qiling."
            ),
            reply_markup=get_back_to_main_keyboard(),
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga rad xabarini yuborishda xatolik: {e}")

    await callback.answer("❌ To'lov rad etildi!")


# ================= TRANSACTION HISTORY ================= #


@router.callback_query(F.data == "wallet:history")
async def cb_wallet_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    from sqlalchemy import desc, select

    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id).order_by(desc(Transaction.created_at)).limit(8)
        )
        txs = list(res.scalars().all())

    if not txs:
        text = "🧾 <b>To'lovlar va tranzaksiyalar tarixi</b>\n\nSizda hali hech qanday tranzaksiya mavjud emas."
    else:
        text = "🧾 <b>Oxirgi tranzaksiyalaringiz tarixi:</b>\n\n"
        for t in txs:
            sign = "+" if t.amount > 0 else ""
            status_icon = "✅" if t.status == "success" else ("⏳" if t.status == "pending" else "❌")
            date_str = t.created_at.strftime("%d.%m.%Y %H:%M")
            text += f"{status_icon} <b>{sign}{t.amount:,.0f} so'm</b> ({t.tx_type})\n   <i>{t.note or ''}</i> — <code>{date_str}</code>\n\n"

    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()
