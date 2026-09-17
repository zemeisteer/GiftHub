from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.keyboards.shop_keyboards import get_shop_main_menu, get_gate_keyboard
from data import config

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """To'liq native Telegram Inline menyu tugmalari"""
    return get_shop_main_menu(is_admin=is_admin)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Faqat /admin komandasi orqali yuboriladigan inline boshqaruv klaviaturasi"""
    from app.keyboards.admin_keyboards import get_admin_main_keyboard
    return get_admin_main_keyboard()
