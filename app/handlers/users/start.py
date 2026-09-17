import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters.command import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext

from database.db import AsyncSessionLocal
from database import queries
from app.keyboards.shop_keyboards import get_shop_main_menu, get_gate_keyboard
from app.keyboards.reply import get_reply_main_keyboard
from app.utils.subscription import verify_user_subscriptions
from data import config

router = Router()
logger = logging.getLogger(__name__)

def build_main_menu_text(first_name: str, balance: float, user_id: int) -> str:
    return (
        f"Assalomu alaykum, <b>{first_name}</b>!\n\n"
        f"⭐ <b>GiftHub (Stellar)</b> — Telegram Stars, Telegram Premium va raqamli sovg'alarni "
        f"eng qulay narxlarda xarid qilish platformasiga xush kelibsiz.\n\n"
        f"💰 Balansingiz: <b>{balance:,.0f} so'm</b>\n"
        f"🆔 Telegram ID: <code>{user_id}</code>\n\n"
        "Xizmatlardan foydalanish uchun quyidagi tugmalardan birini tanlang:"
    )

async def check_admin_status(user_id: int, session) -> bool:
    if str(user_id) in config.ADMINS:
        return True
    user = await queries.get_user_by_id(session, user_id)
    return bool(user and user.role != "user")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
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
        is_admin = await check_admin_status(user_id, session)
        balance = user.balance if user else 0.0

    # Agar barcha majburiy kanallarga a'zo bo'lmagan bo'lsa:
    if not all_passed and missing_channels:
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

    welcome_text = build_main_menu_text(first_name, balance, user_id)

    # Pastki qulay reply tugmalarni ham qo'shib yuboramiz
    await message.answer("✨ Stellar menyusi faollashtirildi.", reply_markup=get_reply_main_keyboard())
    await message.answer(
        text=welcome_text,
        reply_markup=get_shop_main_menu(is_admin=is_admin)
    )


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name or "Foydalanuvchi"

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        is_admin = await check_admin_status(user_id, session)

    text = build_main_menu_text(first_name, balance, user_id)
    kb = get_shop_main_menu(is_admin=is_admin)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.message(F.text.in_(["⭐ Bosh menyu", "Bosh menyu", "🏠 Bosh sahifa"]))
async def user_main_menu_msg(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Foydalanuvchi"

    async with AsyncSessionLocal() as session:
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        is_admin = await check_admin_status(user_id, session)

    text = build_main_menu_text(first_name, balance, user_id)
    await message.answer(text, reply_markup=get_shop_main_menu(is_admin=is_admin))


@router.message(F.text.in_(["💰 Balans", "Balans", "Hamyon"]))
async def user_wallet_shortcut_msg(message: Message, state: FSMContext):
    await state.clear()
    from app.handlers.users.wallet import cb_wallet_view
    # Trigger wallet directly
    class DummyCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.data = "wallet:view"
        async def answer(self, *args, **kwargs):
            pass
    await cb_wallet_view(DummyCallback(message), state)


@router.message(F.text.in_(["👤 Profil", "Profil"]))
async def user_profile_shortcut_msg(message: Message, state: FSMContext):
    await state.clear()
    from app.handlers.users.profile import cb_profile_view
    class DummyCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.data = "profile:view"
        async def answer(self, *args, **kwargs):
            pass
    await cb_profile_view(DummyCallback(message), state, message.bot)


@router.message(F.text.in_(["🛟 Yordam", "Yordam"]))
async def user_help_shortcut_msg(message: Message, state: FSMContext):
    await state.clear()
    from app.handlers.users.profile import cb_help_view
    class DummyCallback:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
            self.data = "help:view"
        async def answer(self, *args, **kwargs):
            pass
    await cb_help_view(DummyCallback(message))


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name or "Foydalanuvchi"

    async with AsyncSessionLocal() as session:
        all_passed, missing_channels = await verify_user_subscriptions(
            bot=callback.bot,
            user_id=user_id,
            session=session
        )
        user = await queries.get_user_by_id(session, user_id)
        balance = user.balance if user else 0.0
        is_admin = await check_admin_status(user_id, session)

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
    welcome_text = build_main_menu_text(first_name, balance, user_id)
    await callback.message.edit_text(
        text=welcome_text,
        reply_markup=get_shop_main_menu(is_admin=is_admin)
    )
