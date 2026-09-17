from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_reply_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Foydalanuvchi doimiy ravishda Telegram pastki panelida ko'rib turishi uchun qulay tezkor Reply klaviatura.
    Web App havolalari yo'q, barchasi bot ichida ishlaydi.
    """
    keyboard = [
        [KeyboardButton(text="⭐ Bosh menyu"), KeyboardButton(text="💰 Balans")],
        [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🛟 Yordam")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
