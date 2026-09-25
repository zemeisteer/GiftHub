import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards.shop_keyboards import get_back_to_main_keyboard, get_profile_keyboard
from app.state.user_states import PromoCodeState
from data import config
from database import queries
from database.db import AsyncSessionLocal

router = Router()
logger = logging.getLogger(__name__)

# ================= PROFILE & REFERRALS ================= #

@router.callback_query(F.data == "profile:view")
async def cb_profile_view(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    bot_username = bot_info.username or "gifthubuzbot"

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        ref_count = user.referrals_count if user else 0
        ref_earnings = user.referral_earnings if user else 0.0
        created_str = user.created_at.strftime("%d.%m.%Y") if user and user.created_at else "Bugun"

    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        "👤 <b>Sizning shaxsiy profilingiz</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Ism: <b>{callback.from_user.full_name}</b>\n"
        f"💰 Balansingiz: <b>{balance:,.0f} so'm</b>\n"
        f"📅 Ro'yxatdan o'tilgan: <b>{created_str}</b>\n"
        "────────────────────\n"
        "👥 <b>Referal dasturi:</b>\n"
        f"• Taklif qilingan do'stlar: <b>{ref_count} ta</b>\n"
        f"• Ishlangan jami daromad: <b>{ref_earnings:,.0f} so'm</b>\n\n"
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        "<i>Do'stlaringiz ushbu havola orqali botga kirib xarid qilishsa, ularning xarididan sizga keshbek beriladi!</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_profile_keyboard(bot_username, user_id))
    except Exception:
        await callback.message.answer(text, reply_markup=get_profile_keyboard(bot_username, user_id))
    await callback.answer()


# ================= PROMO CODE ================= #

@router.callback_query(F.data == "promo:enter")
async def cb_promo_enter(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PromoCodeState.entering_code)
    text = (
        "🎟 <b>Promo-kod kiritish</b>\n\n"
        "Aksiya yoki chegirma promo-kodini kiriting:\n\n"
        "<i>Masalan: STELLAR10 yoki YANGI2026</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()


@router.message(PromoCodeState.entering_code)
async def process_promo_code_text(message: Message, state: FSMContext):
    code = (message.text or "").strip()
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        res = await queries.apply_promo_code(session=session, code=code, user_id=user_id)

    await state.clear()

    if res.get("success"):
        success_msg = res.get('message', "Promo-kod muvaffaqiyatli qo'llandi!")
        await message.answer(
            f"{success_msg}",
            reply_markup=get_back_to_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ <b>Xatolik:</b> {res.get('detail', 'Yaroqsiz promo-kod')}",
            reply_markup=get_back_to_main_keyboard()
        )


# ================= HELP & INFO ================= #

@router.callback_query(F.data == "help:view")
async def cb_help_view(callback: CallbackQuery):
    support_link = config.SUPPORT_URL if config.SUPPORT_URL.startswith("http") else f"https://t.me/{config.SUPPORT_URL.lstrip('@')}"
    extra_news = ""
    if config.NEWS_CHANNEL_URL:
        news_link = config.NEWS_CHANNEL_URL if config.NEWS_CHANNEL_URL.startswith("http") else f"https://t.me/{config.NEWS_CHANNEL_URL.lstrip('@')}"
        extra_news = f"\n📢 Yangiliklar va chegirmalar kanali: {news_link}"

    text = (
        "🛟 <b>Qo'llab-quvvatlash va Ma'lumot</b>\n\n"
        "⭐ <b>GiftHub (Stellar)</b> platformasi orqali Telegram Stars, Telegram Premium va raqamli sovg'alarni eng qulay narxlarda xarid qilishingiz mumkin.\n\n"
        "⚡ <b>Xaridlar qanday amalga oshiriladi?</b>\n"
        "1. «Hamyon» bo'limidan hisobingizni to'ldirasiz (Click, Payme, Karta).\n"
        "2. Stars yoki Premium paketini tanlaysiz.\n"
        "3. Telegram username'ingizni kiritasiz va xaridni tasdiqlaysiz.\n"
        "4. Xaridingiz avtomatik ravishda profilingizga yuboriladi!\n\n"
        f"Savollaringiz yoki takliflaringiz bo'lsa:\n"
        f"👨‍💻 Aloqa: {support_link}{extra_news}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_back_to_main_keyboard())
    await callback.answer()
