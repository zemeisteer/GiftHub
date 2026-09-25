from aiogram import Dispatcher

from app.handlers import channels, groups, users


def setup(dp: Dispatcher):
    users.setup(dp)
    channels.setup(dp)
