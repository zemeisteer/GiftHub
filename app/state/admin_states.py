from aiogram.fsm.state import State, StatesGroup

class AdminBroadcastState(StatesGroup):
    entering_message = State()    # Xabar matni yoki rasm
    confirming = State()          # Tasdiqlash va yuborish

class AdminPriceState(StatesGroup):
    entering_star_cost = State()  # 1 Stars tannarxi (TON yoki so'm)
    entering_margin = State()     # Margin foizi
