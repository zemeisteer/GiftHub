from typing import Any

bot_instance = None
bot_username = None


def get_bot() -> Any:
    return bot_instance


def get_bot_username() -> str | None:
    return bot_username


def set_bot(bot: Any, username: str | None = None) -> None:
    global bot_instance, bot_username
    bot_instance = bot
    if username:
        bot_username = username
