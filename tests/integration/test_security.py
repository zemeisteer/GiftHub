import time

from app.core.security import Permission, has_permission, validate_telegram_init_data
from tests.conftest import make_telegram_init_data


def test_telegram_init_data_valid():
    bot_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    user_id = 987654321
    init_data = make_telegram_init_data(bot_token, user_id=user_id, username="legituser")

    user_info = validate_telegram_init_data(init_data, bot_token=bot_token, max_age_seconds=3600)
    assert user_info["id"] == user_id
    assert user_info["username"] == "legituser"


def test_telegram_init_data_tampered_hash_fails():
    bot_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    init_data = make_telegram_init_data(bot_token, user_id=111, username="attacker")
    # Tamper with the user ID in the query string without updating hash
    tampered_data = init_data.replace("111", "999")

    res = validate_telegram_init_data(tampered_data, bot_token=bot_token)
    assert res is None


def test_telegram_init_data_expired_auth_date():
    bot_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    two_days_ago = int(time.time()) - 172800
    expired_data = make_telegram_init_data(bot_token, user_id=222, auth_date=two_days_ago)

    res = validate_telegram_init_data(expired_data, bot_token=bot_token, max_age_seconds=86400)
    assert res is None


def test_rbac_permissions_hierarchy():
    # Super admin has all permissions
    assert has_permission("super_admin", 1001, Permission.ORDERS_REFUND)
    assert has_permission("super_admin", 1001, Permission.ADMINS_MANAGE)
    assert has_permission("super_admin", 1001, Permission.PRICING_UPDATE)

    # Price admin
    assert has_permission("price_admin", 2002, Permission.PRICING_UPDATE)
    assert not has_permission("price_admin", 2002, Permission.ADMINS_MANAGE)
    assert not has_permission("price_admin", 2002, Permission.ORDERS_REFUND)

    # Support admin
    assert has_permission("support_admin", 3003, Permission.SUPPORT_REPLY)
    assert not has_permission("support_admin", 3003, Permission.PRICING_UPDATE)

    # Normal user
    assert not has_permission("user", 4004, Permission.ORDERS_REFUND)
    assert not has_permission("user", 4004, Permission.PAYMENTS_READ)
