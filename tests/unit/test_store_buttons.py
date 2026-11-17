"""The user store (Web App) must be reachable from the bot: /start menu and the chat Menu button."""

import pytest
from aiogram.types import MenuButtonCommands, MenuButtonWebApp

from app.core.config import settings
from app.keyboards.shop_keyboards import STORE_BUTTON_TEXT, get_chat_menu_button, get_shop_main_menu
from app.utils.notifications import get_store_keyboard

HTTPS_URL = "https://example.trycloudflare.com/app"


def _web_app_buttons(markup):
    return [b for row in markup.inline_keyboard for b in row if b.web_app is not None]


def test_main_menu_starts_with_store_button_when_url_is_https(monkeypatch):
    monkeypatch.setattr(settings, "WEB_APP_URL", HTTPS_URL)
    first = get_shop_main_menu().inline_keyboard[0]
    assert len(first) == 1
    assert first[0].text == STORE_BUTTON_TEXT
    assert first[0].web_app.url == HTTPS_URL


@pytest.mark.parametrize("url", ["", "http://localhost:8000/app", "javascript:alert(1)"])
def test_main_menu_has_no_store_button_without_https_url(monkeypatch, url):
    monkeypatch.setattr(settings, "WEB_APP_URL", url)
    menu = get_shop_main_menu()
    assert _web_app_buttons(menu) == []
    assert menu.inline_keyboard[0][0].callback_data == "shop:stars"


def test_admin_menu_keeps_store_button_and_admin_row(monkeypatch):
    monkeypatch.setattr(settings, "WEB_APP_URL", HTTPS_URL)
    rows = get_shop_main_menu(is_admin=True).inline_keyboard
    assert rows[0][0].web_app.url == HTTPS_URL
    assert rows[-1][0].callback_data == "admin:menu"


def test_chat_menu_button_opens_store_when_url_is_https(monkeypatch):
    monkeypatch.setattr(settings, "WEB_APP_URL", HTTPS_URL)
    button = get_chat_menu_button()
    assert isinstance(button, MenuButtonWebApp)
    assert button.web_app.url == HTTPS_URL


def test_chat_menu_button_falls_back_to_commands_without_https_url(monkeypatch):
    monkeypatch.setattr(settings, "WEB_APP_URL", "http://localhost:8000/app")
    assert isinstance(get_chat_menu_button(), MenuButtonCommands)


def test_notification_store_keyboard_uses_same_button(monkeypatch):
    monkeypatch.setattr(settings, "WEB_APP_URL", HTTPS_URL)
    buttons = _web_app_buttons(get_store_keyboard())
    assert [(b.text, b.web_app.url) for b in buttons] == [(STORE_BUTTON_TEXT, HTTPS_URL)]
