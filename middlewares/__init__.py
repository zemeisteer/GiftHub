from .throttling import ThrottlingMiddleware
from .user_register import UserRegisterMiddleware


def setup_middlewares(dp):
    dp.message.middleware(ThrottlingMiddleware())
    dp.message.middleware(UserRegisterMiddleware())
