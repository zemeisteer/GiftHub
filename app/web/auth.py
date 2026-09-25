from typing import Any

from fastapi import Depends, Header, HTTPException, Query, status

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import has_permission, validate_telegram_init_data
from app.models.user import User
from database import queries

logger = get_logger(__name__)


def validate_init_data(init_data: str, bot_token: str | None = None) -> dict[str, Any] | None:
    """
    Validates Telegram Web App initData string using official HMAC-SHA256
    and validates token age to prevent replay attacks.
    """
    token = bot_token or settings.BOT_TOKEN
    return validate_telegram_init_data(init_data, token)


async def get_current_user(
    x_telegram_init_data: str | None = Header(None),
    x_auth_user_id: str | None = Header(None),
    auth_user_id: int | None = Query(None),
) -> User:
    """
    Authenticates user authoritatively via Telegram WebApp initData HMAC-SHA256 signature.
    Prevents unauthorized header or query user-id spoofing in production environments.
    """
    async with AsyncSessionLocal() as session:
        # 1. Cryptographic Telegram initData validation
        if x_telegram_init_data:
            tg_user = validate_telegram_init_data(x_telegram_init_data)
            if tg_user and "id" in tg_user:
                return await queries.get_or_create_user(
                    session=session,
                    user_id=int(tg_user["id"]),
                    first_name=tg_user.get("first_name", "Foydalanuvchi"),
                    last_name=tg_user.get("last_name"),
                    username=tg_user.get("username"),
                    photo_url=tg_user.get("photo_url"),
                )
            else:
                logger.warning("Telegram initData validation failed or signature expired!")

        # 2. Local development fallback (Strictly disallowed in production!)
        if settings.ENVIRONMENT in ("development", "test"):
            effective_uid = auth_user_id
            if not effective_uid and x_auth_user_id and x_auth_user_id.isdigit():
                effective_uid = int(x_auth_user_id)

            if effective_uid:
                user = await queries.get_user_by_id(session, effective_uid)
                if user:
                    return user
                return await queries.get_or_create_user(
                    session=session,
                    user_id=effective_uid,
                    first_name=f"Foydalanuvchi {effective_uid}",
                    username=f"user_{effective_uid}",
                )

            # Standalone browser demo guest
            demo_uid = 999999999
            user = await queries.get_user_by_id(session, demo_uid)
            if not user:
                user = await queries.get_or_create_user(
                    session=session, user_id=demo_uid, first_name="Mehmon", username="mehmon"
                )
            return user

        # In production without valid initData: Reject
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentifikatsiya talab qilinadi: Telegram initData yaroqsiz.",
        )


async def get_current_admin(
    x_telegram_init_data: str | None = Header(None),
    x_auth_user_id: str | None = Header(None),
    auth_user_id: int | None = Query(None),
) -> User:
    """
    Authenticates administrator and checks admin status authoritatively on the server.
    """
    async with AsyncSessionLocal() as session:
        if x_telegram_init_data:
            tg_user = validate_telegram_init_data(x_telegram_init_data)
            if tg_user and "id" in tg_user:
                user = await queries.get_or_create_user(
                    session=session,
                    user_id=int(tg_user["id"]),
                    first_name=tg_user.get("first_name", "Admin"),
                    last_name=tg_user.get("last_name"),
                    username=tg_user.get("username"),
                    photo_url=tg_user.get("photo_url"),
                )
                if user.role == "user" and user.id not in settings.ADMINS:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN, detail="Ruxsat berilmagan: Siz admin emassiz!"
                    )
                return user

        # Development admin access (only with explicit user id)
        if settings.ENVIRONMENT in ("development", "test"):
            effective_uid = auth_user_id
            if not effective_uid and x_auth_user_id and x_auth_user_id.isdigit():
                effective_uid = int(x_auth_user_id)

            if effective_uid:
                user = await queries.get_user_by_id(session, effective_uid)
                if user and (user.role != "user" or user.id in settings.ADMINS):
                    return user
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Ruxsat berilmagan: Siz admin emassiz!"
                )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Ruxsat berilmagan: Admin huquqi talab qilinadi."
        )


def require_permission(required_perm: str):
    """RBAC dependency ensuring the authenticated admin has the requested permission."""

    async def permission_dependency(admin: User = Depends(get_current_admin)) -> User:
        if not has_permission(admin.role, admin.id, required_perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yetarli huquq mavjud emas: '{required_perm}' talab qilinadi.",
            )
        return admin

    return permission_dependency
