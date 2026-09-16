from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters.command import CommandStart, CommandObject, Command
from database.db import AsyncSessionLocal
from database import queries
from app.keyboards.inline import get_main_menu_keyboard, get_gate_keyboard, get_admin_keyboard
from app.utils.subscription import verify_user_subscriptions
from data import config

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Foydalanuvchi"
    last_name = message.from_user.last_name
    username = message.from_user.username

    referrer_id = None
    args = command.args
    if args:
        if args.startswith("ref_"):
            try:
                referrer_id = int(args.replace("ref_", ""))
            except ValueError:
                pass
        elif args.isdigit():
            referrer_id = int(args)

    async with AsyncSessionLocal() as session:
        user = await queries.get_or_create_user(
            session=session,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            referrer_id=referrer_id
        )

        all_passed, missing_channels = await verify_user_subscriptions(
            bot=message.bot,
            user_id=user_id,
            session=session
        )

    # Agar barcha majburiy kanallarga a'zo bo'lmagan bo'lsa:
    if not all_passed and missing_channels:
        # Pastki reply keyboard (bar) larni tozalab tashlash
        try:
            rm_msg = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
            await rm_msg.delete()
        except Exception:
            pass

        gate_text = (
            f"Assalomu alaykum, <b>{first_name}</b>!\n\n"
            f"⚠️ <b>Botdan to'liq foydalanish uchun quyidagi kanal(lar)ga a'zo bo'ling:</b>\n\n"
            f"Barcha ko'rsatilgan kanallarga a'zo bo'lgach, quyidagi <b>«✅ Tekshirish»</b> tugmasini bosing."
        )
        await message.answer(
            text=gate_text,
            reply_markup=get_gate_keyboard(missing_channels)
        )
        return

    welcome_text = (
        f"Assalomu alaykum, <b>{first_name}</b>!\n\n"
        f"⭐ <b>Stellar</b> — Telegram Stars, Telegram Premium va raqamli sovg'alarni "
        f"hamyonbop narxlarda xarid qilish platformasiga xush kelibsiz.\n\n"
        f"Quyidagi <b>⭐ Stellar Web App</b> tugmasini bosib do'konga kiring:"
    )

    await message.answer(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard()
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """
    Faqat vakolatli adminlar uchun boshqaruv panelini ochish.
    Asosiy start menyusida ko'rinmaydi.
    """
    user_id = message.from_user.id
    is_admin = str(user_id) in config.ADMINS
    if not is_admin:
        async with AsyncSessionLocal() as session:
            user = await queries.get_user_by_id(session, user_id)
            if user and user.role != "user":
                is_admin = True

    if not is_admin:
        await message.answer("⛔ <b>Kechirasiz!</b> Bu buyruq faqat bot adminlari uchun mo'ljallangan.")
        return

    await message.answer(
        "⚙ <b>Stellar Boshqaruv Paneli (Admin Panel)</b>\n\n"
        "Narxlar, buyurtmalar, majburiy obuna, foydalanuvchilar va xabarnomalarni boshqarish uchun "
        "quyidagi tugmani bosing:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text.in_(["👤 Profil", "Profil"]))
async def user_profile_msg(message: Message):
    async with AsyncSessionLocal() as session:
        all_passed, missing_channels = await verify_user_subscriptions(
            bot=message.bot,
            user_id=message.from_user.id,
            session=session
        )
        if not all_passed and missing_channels:
            await message.answer(
                "⚠️ <b>Botdan foydalanish uchun quyidagi kanal(lar)ga a'zo bo'ling:</b>",
                reply_markup=get_gate_keyboard(missing_channels)
            )
            return

        user = await queries.get_user_by_id(session, message.from_user.id)
        bal = round(user.balance) if user else 0
        ref_count = user.referrals_count if user else 0

    await message.answer(
        f"👤 <b>Sizning profilingiz:</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💰 Balansingiz: <b>{bal:,} so'm</b>\n"
        f"👥 Taklif qilgan do'stlaringiz: <b>{ref_count} ta</b>\n\n"
        f"Barcha xizmatlardan foydalanish uchun <b>⭐ Do'konni ochish</b> tugmasini bosing.",
        reply_markup=get_main_menu_keyboard()
    )

@router.message(F.text.in_(["🛟 Yordam", "Yordam"]))
async def user_help_msg(message: Message):
    async with AsyncSessionLocal() as session:
        all_passed, missing_channels = await verify_user_subscriptions(
            bot=message.bot,
            user_id=message.from_user.id,
            session=session
        )
        if not all_passed and missing_channels:
            await message.answer(
                "⚠️ <b>Botdan foydalanish uchun quyidagi kanal(lar)ga a'zo bo'ling:</b>",
                reply_markup=get_gate_keyboard(missing_channels)
            )
            return

    if not config.SUPPORT_URL:
        await message.answer("🛟 <b>Qo'llab-quvvatlash xizmati:</b>\n\nHozirda maxsus yordam xizmati sozlanmagan.")
        return

    support_link = config.SUPPORT_URL if config.SUPPORT_URL.startswith("http") else f"https://t.me/{config.SUPPORT_URL.lstrip('@')}"
    extra_text = ""
    if config.NEWS_CHANNEL_URL:
        news_link = config.NEWS_CHANNEL_URL if config.NEWS_CHANNEL_URL.startswith("http") else f"https://t.me/{config.NEWS_CHANNEL_URL.lstrip('@')}"
        extra_text = f"\n📣 Yangiliklar kanali: {news_link}"

    await message.answer(
        f"🛟 <b>Qo'llab-quvvatlash xizmati</b>\n\n"
        f"Savollaringiz yoki to'lov bo'yicha yordam kerak bo'lsa, ma'muriyatga murojaat qiling:\n"
        f"👉 <a href='{support_link}'>{config.SUPPORT_URL}</a>{extra_text}"
    )

@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name or "Foydalanuvchi"

    async with AsyncSessionLocal() as session:
        all_passed, missing_channels = await verify_user_subscriptions(
            bot=callback.bot,
            user_id=user_id,
            session=session
        )

    if not all_passed and missing_channels:
        await callback.answer(
            "❌ Barcha kanallarga a'zo bo'lmadingiz! Iltimos, ro'yxatdagi barcha kanallarga a'zo bo'ling.",
            show_alert=True
        )
        try:
            await callback.message.edit_reply_markup(
                reply_markup=get_gate_keyboard(missing_channels)
            )
        except Exception:
            pass
        return

    await callback.answer("✅ A'zolik tasdiqlandi!")
    welcome_text = (
        f"Assalomu alaykum, <b>{first_name}</b>!\n\n"
        f"⭐ <b>Stellar</b> — Telegram Stars, Telegram Premium va raqamli sovg'alarni "
        f"hamyonbop narxlarda xarid qilish platformasiga xush kelibsiz.\n\n"
        f"Quyidagi <b>⭐ Stellar Web App</b> tugmasini bosib do'konga kiring:"
    )
    await callback.message.edit_text(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard()
    )
