"""Shared fakes for the Telegram gifts feature (mirror aiogram 3 types)."""

from aiogram.types import Gift, Gifts, StarAmount, Sticker


def make_gift(
    id: str,
    star_count: int = 15,
    emoji: str | None = "🧸",
    is_premium: bool = False,
    total_count: int | None = None,
    remaining_count: int | None = None,
) -> Gift:
    sticker = Sticker(
        file_id=f"file-{id}",
        file_unique_id=f"uniq-{id}",
        type="regular",
        width=512,
        height=512,
        is_animated=False,
        is_video=False,
        emoji=emoji,
    )
    return Gift(
        id=id,
        sticker=sticker,
        star_count=star_count,
        is_premium=is_premium or None,
        total_count=total_count,
        remaining_count=remaining_count,
    )


class FakeGiftBot:
    """Stands in for aiogram.Bot: gifts catalog, Stars balance, sendGift, messages."""

    def __init__(self, available: list[Gift] | None = None, balance: int | None = 1000):
        self.available = list(available or [])
        self.balance = balance
        self.sent: list[dict] = []
        self.messages: list[dict] = []
        # Exceptions raised (one per call, in order) by send_gift before it succeeds.
        self.send_errors: list[Exception] = []

    async def get_available_gifts(self, **kw) -> Gifts:
        return Gifts(gifts=list(self.available))

    async def get_my_star_balance(self, **kw) -> StarAmount:
        return StarAmount(amount=self.balance)

    async def send_gift(self, user_id: int, gift_id: str, **kw) -> bool:
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.sent.append({"user_id": user_id, "gift_id": gift_id, **kw})
        return True

    async def send_message(self, chat_id: int, text: str, **kw) -> None:
        self.messages.append({"chat_id": chat_id, "text": text, **kw})
