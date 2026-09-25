from aiogram import Dispatcher

from .channel_events import router as channel_router


def setup(dp: Dispatcher):
    dp.include_router(channel_router)
