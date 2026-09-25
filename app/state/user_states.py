from aiogram.fsm.state import State, StatesGroup


class StarsPurchaseState(StatesGroup):
    entering_amount = State()  # Agar "✍️ Boshqa miqdor" tanlansa
    entering_recipient = State()  # Kimga (@username)
    confirming = State()  # Xaridni tasdiqlash


class PremiumPurchaseState(StatesGroup):
    entering_recipient = State()  # Kimga (@username)
    confirming = State()  # Xaridni tasdiqlash


class GiftPurchaseState(StatesGroup):
    entering_recipient = State()  # Kimga (@username)
    confirming = State()  # Xaridni tasdiqlash


class BalanceTopupState(StatesGroup):
    entering_amount = State()  # "✍️ Boshqa summa" kiritish
    selecting_method = State()  # To'lov usulini tanlash (Click, Payme, Karta)
    uploading_receipt = State()  # Karta orqali to'lovda chek (skrinshot) yuborish


class PromoCodeState(StatesGroup):
    entering_code = State()  # Promo-kod kiritish


class ServicePurchaseState(StatesGroup):
    entering_details = State()  # Hisob / login / username kiritish
    confirming = State()  # Xaridni tasdiqlash
