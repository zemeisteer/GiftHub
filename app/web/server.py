import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    GiftHubException,
    InsufficientBalanceError,
    PriceExpiredError,
)
from app.core.logging import get_logger
from app.core.security import Permission, has_permission, validate_telegram_init_data
from app.models import (
    BroadcastDraft,
    ChannelRequirement,
    Order,
    OrderStatus,
    PaymentSetting,
    ReferralSetting,
    SupportTicket,
    TicketMessage,
    User,
)
from app.services.fulfillment.service import fulfillment_service
from app.services.notifications.service import notification_service
from app.services.orders.service import order_service
from app.services.payments import (
    generate_click_link,
    generate_payme_link,
    handle_autopaycard_webhook,
    handle_payme_request,
    process_click_complete,
    process_click_prepare,
    verify_payme_auth,
)
from app.services.pricing.service import pricing_service
from app.services.promotions.service import promotion_service
from app.services.referrals.service import referral_service
from app.services.support.service import support_service
from app.services.wallet.service import wallet_service
from app.utils.notifications import (
    send_admin_order_alert,
    send_order_created_notification,
    send_order_status_update_notification,
)
from database import queries

logger = get_logger("GiftHubAPI")

app = FastAPI(
    title="GiftHub Web App & API",
    description="Official API for GiftHub — Telegram Stars, Premium, Gifts & Services Platform",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    from app.core.correlation import set_correlation_id
    incoming_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
    cid = set_correlation_id(incoming_id)
    response: Response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    path = request.url.path
    exempt_prefixes = ("/health", "/ready", "/admin", "/webhook", "/static", "/docs", "/openapi.json")
    if not any(path.startswith(p) for p in exempt_prefixes):
        try:
            from app.services.feature_flags.service import feature_flag_service
            async with AsyncSessionLocal() as session:
                if await feature_flag_service.is_maintenance_mode(session):
                    return JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={
                            "success": False,
                            "maintenance": True,
                            "detail": "Platforma texnik ta'mirlash rejimida. Tez orada qayta ishga tushadi."
                        }
                    )
        except Exception:
            pass
    return await call_next(request)


# Include Versioned /api/v1 Router
from app.api.v1.router import router as v1_router

app.include_router(v1_router, prefix="/api/v1")

# Reference to the running bot instance (set during startup in main.py)
bot_instance = None
bot_username = None


def set_bot(bot, username: str | None = None):
    global bot_instance, bot_username
    bot_instance = bot
    if username:
        bot_username = username


# ================= TELEGRAM WEBHOOK (Req 14) ================= #

@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token")
):
    """
    Receives Telegram updates in production Webhook mode.
    Validated with X-Telegram-Bot-Api-Secret-Token.
    """
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Unauthorized webhook request with invalid secret token.")
            raise HTTPException(status_code=403, detail="Invalid webhook secret token.")

    update_dict = await request.json()
    if bot_instance:
        from aiogram.types import Update

        from main import dp
        update_obj = Update(**update_dict)
        await dp.feed_webhook_update(bot_instance, update_obj)
        return {"ok": True}
    return {"ok": False, "error": "Bot instance not initialized"}



# ================= HEALTH & READINESS ================= #

@app.get("/health")
async def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "app": "GiftHub",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/ready")
async def readiness_check():
    """Readiness probe verifying database and redis connectivity."""
    db_ok = False
    redis_ok = False

    # Check Database
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"Readiness DB probe failed: {e}")

    # Check Redis
    from app.core.redis import get_redis_client
    r_client = get_redis_client()
    if r_client:
        try:
            pong = await r_client.ping()
            redis_ok = bool(pong)
        except Exception:
            redis_ok = False
    else:
        # If Redis is not configured in local environment, treat as optional
        redis_ok = True if settings.ENVIRONMENT != "production" else False

    is_ready = db_ok and (redis_ok or settings.ENVIRONMENT != "production")
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
            "environment": settings.ENVIRONMENT
        }
    )


@app.get("/api/bot-info")
async def get_bot_info():
    uname = bot_username
    if not uname and bot_instance:
        try:
            me = await bot_instance.get_me()
            uname = me.username
        except Exception:
            pass
    return {"username": uname or "gifthub_bot"}


# ================= AUTHENTICATION & RBAC DEPENDENCIES ================= #

async def get_current_user(
    x_telegram_init_data: str | None = Header(None),
    x_auth_user_id: str | None = Header(None),
    auth_user_id: int | None = Query(None)
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
                    photo_url=tg_user.get("photo_url")
                )
            else:
                logger.warning("Telegram initData validation failed or signature expired!")

        # 2. Local development fallback (Disallowed in production!)
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
                    username=f"user_{effective_uid}"
                )

            # Standalone browser demo guest
            demo_uid = 999999999
            user = await queries.get_user_by_id(session, demo_uid)
            if not user:
                user = await queries.get_or_create_user(
                    session=session,
                    user_id=demo_uid,
                    first_name="Mehmon",
                    username="mehmon"
                )
            return user

        # In production without valid initData: Reject
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentifikatsiya talab qilinadi: Telegram initData yaroqsiz."
        )


async def get_current_admin(
    x_telegram_init_data: str | None = Header(None),
    x_auth_user_id: str | None = Header(None),
    auth_user_id: int | None = Query(None)
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
                    photo_url=tg_user.get("photo_url")
                )
                if user.role == "user" and user.id not in settings.ADMINS:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Ruxsat berilmagan: Siz admin emassiz!"
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
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Ruxsat berilmagan: Siz admin emassiz!"
                )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ruxsat berilmagan: Admin huquqi talab qilinadi."
        )


def require_permission(required_perm: str):
    """RBAC dependency ensuring the authenticated admin has the requested permission."""
    async def permission_dependency(admin: User = Depends(get_current_admin)) -> User:
        if not has_permission(admin.role, admin.id, required_perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yetarli huquq mavjud emas: '{required_perm}' talab qilinadi."
            )
        return admin
    return permission_dependency


# ================= USER API ROUTES ================= #

@app.get("/api/user/me")
async def get_me(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func, select
        # Count total orders
        res = await session.execute(
            select(func.count(Order.id)).where(Order.user_id == user.id)
        )
        orders_count = res.scalar() or 0

        # Count completed orders
        res_done = await session.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user.id,
                Order.status.in_([OrderStatus.COMPLETED, "done"])
            )
        )
        completed_orders = res_done.scalar() or 0

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "photo_url": user.photo_url,
            "balance": round(float(user.balance)),
            "role": user.role,
            "referrals_count": user.referrals_count,
            "referral_earnings": round(float(user.referral_earnings)),
            "orders_count": orders_count,
            "completed_orders": completed_orders,
            "created_at": user.created_at.strftime("%d %b %Y") if user.created_at else ""
        }


@app.get("/api/gate/check")
async def check_gate_channels(user: User = Depends(get_current_user)):
    """Checks mandatory subscription conditions (gate screen)."""
    async with AsyncSessionLocal() as session:
        if user.id in settings.ADMINS or (user.role and user.role != "user"):
            return {"all_passed": True, "channels": []}

        channels = await queries.list_channels(session, active_only=True)
        results = []
        all_passed = True

        for ch in channels:
            if ch.is_detected:
                continue

            is_member = False
            if ch.req_type == "external":
                is_member = True
            elif ch.req_type == "join_request":
                has_req = False
                if ch.chat_id:
                    has_req = await queries.has_user_join_request(session, user.id, ch.chat_id)
                if not has_req and bot_instance and ch.chat_id:
                    try:
                        chat_member = await bot_instance.get_chat_member(chat_id=ch.chat_id, user_id=user.id)
                        has_req = chat_member.status in ["creator", "administrator", "member", "restricted"]
                    except Exception:
                        has_req = False
                is_member = has_req
            else:
                target = ch.chat_id
                if not target and ch.username_or_link:
                    val = ch.username_or_link.strip()
                    if val.startswith("@"):
                        target = val
                    elif "t.me/" in val:
                        part = val.rstrip("/").split("/")[-1]
                        if not part.startswith("+"):
                            target = f"@{part}"

                if bot_instance and target:
                    try:
                        chat_member = await bot_instance.get_chat_member(chat_id=target, user_id=user.id)
                        is_member = chat_member.status in ["creator", "administrator", "member", "restricted"]
                    except Exception:
                        is_member = False
                else:
                    is_member = True

            if not is_member:
                all_passed = False

            channel_title = ch.title if (ch.title and ch.title.strip()) else ch.username_or_link
            ch_link = ch.username_or_link
            if not ch_link.startswith("http"):
                ch_link = f"https://t.me/{ch_link.lstrip('@')}"

            results.append({
                "id": ch.id,
                "title": channel_title,
                "link": ch_link,
                "display_name": channel_title,
                "username": ch.username_or_link,
                "type": ch.req_type,
                "passed": is_member
            })

        return {"all_passed": all_passed, "channels": results}


@app.get("/api/products")
async def get_products(stars_amount: int | None = None):
    """Returns calculated product packages for Stars, Premium, and Gifts with authoritative pricing."""
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)

        popular_amounts = [50, 100, 250, 500, 1000]
        stars_packages = []
        for amt in popular_amounts:
            calc = pricing_service.calculate_stars_price(amt, pricing)
            stars_packages.append({
                "amount": amt,
                "name": f"{amt} ⭐",
                "price_uzs": calc["total_price_uzs"],
                "discount_pct": calc["discount_percent"],
                "formatted_price": calc["formatted_price"]
            })

        custom_calc = None
        if stars_amount and stars_amount > 0:
            custom_calc = pricing_service.calculate_stars_price(stars_amount, pricing)

        try:
            prem_data = json.loads(pricing.premium_prices_json)
        except Exception:
            prem_data = {"3": 142000, "6": 210000, "12": 380000}

        premium_packages = [
            {"months": 3, "name": "Premium — 3 oy", "price_uzs": prem_data.get("3", 142000), "icon": "💎"},
            {"months": 6, "name": "Premium — 6 oy", "price_uzs": prem_data.get("6", 210000), "icon": "💎"},
            {"months": 12, "name": "Premium — 12 oy", "price_uzs": prem_data.get("12", 380000), "icon": "👑"}
        ]

        try:
            gifts_list = json.loads(pricing.gifts_json) if pricing and pricing.gifts_json else []
        except Exception:
            gifts_list = []

        payment_setting = await session.get(PaymentSetting, 1)
        payment_methods = []
        card_info = None
        if payment_setting:
            if getattr(payment_setting, "card_active", True):
                c_num = getattr(payment_setting, "card_number", "8600 1234 5678 9012")
                c_holder = getattr(payment_setting, "card_holder", "ANVAR S.")
                b_name = getattr(payment_setting, "bank_name", "TBC Bank")
                card_info = {"card_number": c_num, "card_holder": c_holder, "bank_name": b_name}
                payment_methods.append({
                    "id": "card",
                    "name": "Karta orqali to'lov",
                    "icon": "💳",
                    "type": "card",
                    "card_number": c_num,
                    "card_holder": c_holder,
                    "bank_name": b_name
                })
            if payment_setting.click_active:
                payment_methods.append({"id": "click", "name": "Click", "icon": "💳", "type": "official"})
            if payment_setting.payme_active:
                payment_methods.append({"id": "payme", "name": "Payme", "icon": "💳", "type": "official"})
            if payment_setting.autopaycard_active:
                payment_methods.append({"id": "autopaycard", "name": "AutoPayCard (Karta)", "icon": "⚠️", "type": "backup"})

        star_base_cost = float(pricing.star_unit_price_uzs or 180.0)
        margin = float(pricing.margin_percent or 15.0)
        star_sell = round(star_base_cost * (1 + margin / 100), 2)

        return {
            "stars_unit_cost_uzs": star_base_cost,
            "stars_unit_sell_uzs": star_sell,
            "stars_packages": stars_packages,
            "custom_stars_calc": custom_calc,
            "premium_packages": premium_packages,
            "gifts": gifts_list,
            "payment_methods": payment_methods,
            "card_info": card_info
        }


class TopupRequest(BaseModel):
    amount: float
    method: str # click, payme, autopaycard


@app.post("/api/wallet/topup")
async def topup_wallet(req: TopupRequest, user: User = Depends(get_current_user)):
    """
    Secure topup endpoint: generates official payment checkout link.
    Prevents arbitrary client balance credit vulnerability.
    """
    if req.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimal to'ldirish summasi: 1 000 so'm")

    dec_amount = Decimal(str(req.amount))

    # In local development mode with demo accounts, allow simulated credit
    if settings.ENVIRONMENT in ("development", "test") and req.method == "test_demo":
        async with AsyncSessionLocal() as session:
            updated_user, tx = await wallet_service.credit_balance(
                session=session,
                user_id=user.id,
                amount=dec_amount,
                tx_type="topup",
                reference_type="dev_mock",
                note=f"Test demo hisob to'ldirildi ({req.method})"
            )
            await session.commit()
            return {
                "success": True,
                "dev_mode": True,
                "new_balance": round(float(updated_user.balance)),
                "amount": float(dec_amount),
                "method": req.method,
                "message": f"[DEV] Hamyon to'ldirildi: +{dec_amount:,.0f} so'm"
            }

    # Generate checkout link for the requested payment provider
    if req.method == "click":
        url = generate_click_link(user.id, float(dec_amount))
        return {"success": True, "method": "click", "checkout_url": url, "amount": float(dec_amount)}
    elif req.method == "payme":
        url = generate_payme_link(user.id, float(dec_amount))
        return {"success": True, "method": "payme", "checkout_url": url, "amount": float(dec_amount)}
    elif req.method == "autopaycard":
        async with AsyncSessionLocal() as session:
            ps = await session.get(PaymentSetting, 1)
            card_last4 = ps.autopaycard_last4 if ps else "6412"
            return {
                "success": True,
                "method": "autopaycard",
                "instructions": f"Ushbu summani ko'rsatilgan Uzcard kartaga o'tkazing: **** **** **** {card_last4}",
                "amount": float(dec_amount)
            }
    else:
        raise HTTPException(status_code=400, detail="Noma'lum to'lov usuli")


class CheckoutLinkRequest(BaseModel):
    amount: float
    method: str


@app.post("/api/wallet/checkout-link")
async def get_checkout_link(req: CheckoutLinkRequest, user: User = Depends(get_current_user)):
    if req.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimal to'ldirish summasi: 1 000 so'm")

    dec_amount = Decimal(str(req.amount))
    if req.method == "click":
        url = generate_click_link(user.id, float(dec_amount))
        return {"success": True, "method": "click", "checkout_url": url, "amount": float(dec_amount)}
    elif req.method == "payme":
        url = generate_payme_link(user.id, float(dec_amount))
        return {"success": True, "method": "payme", "checkout_url": url, "amount": float(dec_amount)}
    elif req.method == "autopaycard":
        async with AsyncSessionLocal() as session:
            ps = await session.get(PaymentSetting, 1)
            card_last4 = ps.autopaycard_last4 if ps else "6412"
            return {
                "success": True,
                "method": "autopaycard",
                "instructions": f"Ushbu summani ko'rsatilgan Uzcard kartaga o'tkazing: **** **** **** {card_last4}",
                "amount": float(dec_amount)
            }
    else:
        raise HTTPException(status_code=400, detail="Noma'lum to'lov usuli")


# ================= OFFICIAL PAYMENT WEBHOOKS ================= #

@app.post("/api/payments/click")
@app.post("/api/payments/click/prepare")
@app.post("/api/payments/click/complete")
async def click_webhook_handler(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        form = await request.form()
        data = dict(form)

    action = int(data.get("action", 0))
    async with AsyncSessionLocal() as session:
        if action == 0:
            result = await process_click_prepare(session, data)
        elif action == 1:
            result = await process_click_complete(session, data, bot=bot_instance)
        else:
            result = {"error": -3, "error_note": "Action not found"}
        return JSONResponse(result)


@app.post("/api/payments/payme")
async def payme_webhook_handler(request: Request):
    auth_header = request.headers.get("authorization")
    if not verify_payme_auth(auth_header):
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32504, "message": "Avtorizatsiya xatosi"}
        })

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "JSON xatosi"}
        })

    async with AsyncSessionLocal() as session:
        result = await handle_payme_request(session, payload, bot=bot_instance)
        return JSONResponse(result)


@app.post("/api/payments/autopaycard")
async def autopaycard_webhook_handler(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = dict(await request.form())

    async with AsyncSessionLocal() as session:
        result = await handle_autopaycard_webhook(session, payload, bot=bot_instance)
        return JSONResponse(result)


# ================= CHECKOUT & ORDERS ================= #

class PriceLockRequest(BaseModel):
    product_type: str
    amount: int = 1


@app.post("/api/checkout/price-lock")
async def create_price_lock_endpoint(req: PriceLockRequest, user: User = Depends(get_current_user)):
    """Creates a temporary price lock for checkout."""
    async with AsyncSessionLocal() as session:
        lock = await pricing_service.create_price_lock(
            session=session,
            product_type=req.product_type,
            amount=req.amount,
            user_id=user.id
        )
        now = datetime.now(timezone.utc)
        time_left = max(0, int((lock.expires_at - now).total_seconds()))
        return {
            "success": True,
            "lock_id": lock.id,
            "product_type": lock.product_type,
            "amount": lock.amount,
            "total_price_uzs": float(lock.total_price),
            "unit_price_uzs": float(lock.unit_price),
            "expires_at": lock.expires_at.isoformat(),
            "time_left_seconds": time_left
        }


class PurchaseRequest(BaseModel):
    product_type: str # stars, premium, gift, service
    item_title: str
    amount: int = 1
    recipient_username: str | None = None
    promo_code: str | None = None
    price_lock_id: str | None = None


@app.post("/api/orders/create")
async def create_order_endpoint(req: PurchaseRequest, user: User = Depends(get_current_user)):
    """
    Authoritative order creation endpoint.
    Client-supplied price is strictly ignored; backend calculates authoritative price.
    """
    async with AsyncSessionLocal() as session:
        try:
            order, bonus, referrer = await order_service.create_order(
                session=session,
                user_id=user.id,
                product_type=req.product_type,
                item_title=req.item_title,
                amount=req.amount,
                recipient_username=req.recipient_username,
                promo_code_str=req.promo_code,
                price_lock_id=req.price_lock_id
            )
        except InsufficientBalanceError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except PriceExpiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except GiftHubException as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)

        # Trigger Fragment automated delivery asynchronously
        from app.services.fragment import fragment_client
        asyncio.create_task(
            fragment_client.fulfill_order(order_id=order.id, bot=bot_instance)
        )

        # Trigger notifications
        u = await queries.get_user_by_id(session, user.id)
        current_bal = float(u.balance) if u else 0.0

        asyncio.create_task(
            send_order_created_notification(
                bot=bot_instance,
                user_id=user.id,
                order_code=order.order_code,
                item_title=order.item_title,
                amount=order.amount,
                total_price=float(order.total_price),
                status=order.status,
                new_balance=current_bal,
                recipient_username=req.recipient_username,
                buyer_username=user.username
            )
        )
        asyncio.create_task(
            send_admin_order_alert(
                bot=bot_instance,
                admin_ids=settings.ADMINS,
                user_name=user.first_name,
                user_id=user.id,
                username=user.username,
                order_code=order.order_code,
                item_title=order.item_title,
                amount=order.amount,
                total_price=float(order.total_price),
                cost_price=float(order.cost_price),
                status=order.status,
                recipient_username=req.recipient_username
            )
        )

        return {
            "success": True,
            "order_code": order.order_code,
            "order_id": order.id,
            "product_type": order.product_type,
            "item_title": order.item_title,
            "total_price": float(order.total_price),
            "status": order.status,
            "new_balance": round(current_bal)
        }


@app.get("/api/orders/history")
async def get_order_history(
    status: str | None = None,
    user: User = Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_user_orders(session, user.id, status=status)
        return [
            {
                "id": o.id,
                "order_code": o.order_code,
                "product_type": o.product_type,
                "item_title": o.item_title,
                "amount": o.amount,
                "total_price": round(float(o.total_price)),
                "status": o.status,
                "recipient_username": o.recipient_username,
                "created_at": o.created_at.strftime("%d %b, %H:%M") if o.created_at else ""
            }
            for o in orders
        ]


class PromoApplyRequest(BaseModel):
    code: str
    order_total: float = 0.0
    product_type: str = "all"


@app.post("/api/promo/apply")
async def apply_promocode_endpoint(req: PromoApplyRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        try:
            res = await promotion_service.apply_promo_code(
                session=session,
                code_str=req.code,
                user_id=user.id,
                order_total=Decimal(str(req.order_total)),
                product_type=req.product_type
            )
            return res
        except GiftHubException as e:
            return {"success": False, "detail": e.message}


@app.get("/api/referrals/analytics")
async def get_referral_analytics_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        analytics = await referral_service.get_referral_analytics(session, user.id)
        return analytics


# ================= IN-APP NOTIFICATIONS ================= #

@app.get("/api/notifications")
async def get_notifications_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        notifs = await notification_service.list_notifications(session, user.id)
        return [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "related_entity": n.related_entity,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%d %b, %H:%M") if n.created_at else ""
            }
            for n in notifs
        ]


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read_endpoint(notification_id: int, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ok = await notification_service.mark_as_read(session, notification_id, user.id)
        return {"success": ok}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        count = await notification_service.mark_all_as_read(session, user.id)
        return {"success": True, "count": count}


# ================= SUPPORT TICKETS ================= #

class TicketCreateRequest(BaseModel):
    subject: str
    category: str = "other"
    message: str
    order_id: int | None = None


@app.post("/api/support/tickets")
async def create_ticket_endpoint(req: TicketCreateRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await support_service.create_ticket(
            session=session,
            user_id=user.id,
            subject=req.subject,
            category=req.category,
            initial_message=req.message,
            order_id=req.order_id
        )
        return {"success": True, "ticket_id": ticket.id}


@app.get("/api/support/tickets")
async def list_user_tickets_endpoint(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        tickets = await support_service.list_user_tickets(session, user.id)
        return [
            {
                "id": t.id,
                "subject": t.subject,
                "category": t.category,
                "status": t.status,
                "order_id": t.order_id,
                "created_at": t.created_at.strftime("%d %b, %H:%M") if t.created_at else ""
            }
            for t in tickets
        ]


@app.get("/api/support/tickets/{ticket_id}/messages")
async def get_ticket_messages_endpoint(ticket_id: int, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket or (ticket.user_id != user.id and user.role == "user" and user.id not in settings.ADMINS):
            raise HTTPException(status_code=404, detail="Murojaat topilmadi")

        from sqlalchemy import select
        res = await session.execute(
            select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
        )
        messages = res.scalars().all()
        return [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "sender_type": m.sender_type,
                "text": m.text,
                "created_at": m.created_at.strftime("%d %b, %H:%M") if m.created_at else ""
            }
            for m in messages
        ]


class TicketReplyRequest(BaseModel):
    text: str


@app.post("/api/support/tickets/{ticket_id}/reply")
async def reply_ticket_endpoint(ticket_id: int, req: TicketReplyRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Murojaat topilmadi")

        sender_type = "admin" if (user.role != "user" or user.id in settings.ADMINS) else "user"
        msg = await support_service.add_reply(
            session=session,
            ticket_id=ticket_id,
            sender_id=user.id,
            sender_type=sender_type,
            text=req.text
        )
        return {"success": True, "message_id": msg.id}


# ================= ADMIN APIS WITH RBAC ================= #

@app.get("/api/admin/stats")
async def get_admin_dashboard(admin: User = Depends(require_permission(Permission.ANALYTICS_READ))):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func, select
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        users_total = (await session.execute(select(func.count(User.id)))).scalar() or 0
        new_users_week = (await session.execute(select(func.count(User.id)).where(User.created_at >= week_ago))).scalar() or 0

        sales_total = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        costs_total = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        profit_total = max(0.0, float(sales_total) - float(costs_total))

        ref_sales_count = (await session.execute(
            select(func.count(Order.id))
            .select_from(Order)
            .join(User, Order.user_id == User.id)
            .where(User.referrer_id.isnot(None), Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0

        stars_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "stars", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        stars_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "stars", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        prem_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "premium", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        prem_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "premium", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        gifts_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "gift", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0
        gifts_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "gift", Order.status.in_([OrderStatus.COMPLETED, "done"]))
        )).scalar() or 0.0

        month_ago = now - timedelta(days=30)
        orders_q = await session.execute(
            select(Order.total_price, Order.created_at, Order.completed_at)
            .where(Order.status.in_([OrderStatus.COMPLETED, "done"]), Order.created_at >= month_ago)
        )
        done_orders = orders_q.all()

        today_date = now.date()
        daily_chart = [
            {"label": "00-04", "start_h": 0, "end_h": 4, "sales": 0, "count": 0},
            {"label": "04-08", "start_h": 4, "end_h": 8, "sales": 0, "count": 0},
            {"label": "08-12", "start_h": 8, "end_h": 12, "sales": 0, "count": 0},
            {"label": "12-16", "start_h": 12, "end_h": 16, "sales": 0, "count": 0},
            {"label": "16-20", "start_h": 16, "end_h": 20, "sales": 0, "count": 0},
            {"label": "20-24", "start_h": 20, "end_h": 24, "sales": 0, "count": 0},
        ]
        for row in done_orders:
            dt = row.completed_at or row.created_at
            if dt and dt.date() == today_date:
                h = dt.hour
                for slot in daily_chart:
                    if slot["start_h"] <= h < slot["end_h"]:
                        slot["sales"] += round(float(row.total_price or 0))
                        slot["count"] += 1
                        break

        uz_weekdays = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
        weekly_chart = []
        for d in range(6, -1, -1):
            target_dt = (now - timedelta(days=d)).date()
            day_label = uz_weekdays[target_dt.weekday()]
            day_sales = 0
            day_count = 0
            for row in done_orders:
                dt = row.completed_at or row.created_at
                if dt and dt.date() == target_dt:
                    day_sales += round(float(row.total_price or 0))
                    day_count += 1
            weekly_chart.append({
                "label": day_label,
                "date": target_dt.strftime("%d-%m"),
                "sales": day_sales,
                "count": day_count
            })

        monthly_chart = []
        for w in range(3, -1, -1):
            start_date = (now - timedelta(days=(w+1)*7)).date()
            end_date = (now - timedelta(days=w*7)).date()
            week_label = f"{4-w}-hafta"
            week_sales = 0
            week_count = 0
            for row in done_orders:
                dt = row.completed_at or row.created_at
                if dt and start_date < dt.date() <= end_date:
                    week_sales += round(float(row.total_price or 0))
                    week_count += 1
            monthly_chart.append({
                "label": week_label,
                "range": f"{start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m')}",
                "sales": week_sales,
                "count": week_count
            })

        return {
            "users_total": users_total,
            "new_users_week": new_users_week,
            "sales_total": round(float(sales_total)),
            "profit_total": round(float(profit_total)),
            "ref_sales_count": ref_sales_count,
            "breakdown": [
                {"name": "Stars (jami)", "sales": round(float(stars_sales)), "cost": round(float(stars_cost)), "profit": round(float(stars_sales) - float(stars_cost))},
                {"name": "Premium (jami)", "sales": round(float(prem_sales)), "cost": round(float(prem_cost)), "profit": round(float(prem_sales) - float(prem_cost))},
                {"name": "Sovg'alar (jami)", "sales": round(float(gifts_sales)), "cost": round(float(gifts_cost)), "profit": round(float(gifts_sales) - float(gifts_cost))}
            ],
            "charts": {"daily": daily_chart, "weekly": weekly_chart, "monthly": monthly_chart}
        }


@app.get("/api/admin/pricing")
async def get_admin_pricing(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        frag_star_base = float(pricing.star_unit_price_uzs or 180.0)
        margin = float(pricing.margin_percent or 15.0)
        unit_sell = frag_star_base * (1 + margin / 100)

        discounts = []
        try:
            discounts = json.loads(pricing.stars_discounts_json) if pricing.stars_discounts_json else []
        except Exception:
            discounts = []

        prem_bases = {"3": 138000, "6": 205000, "12": 375000}
        prem_prices = {}
        try:
            prem_prices = json.loads(pricing.premium_prices_json) if pricing.premium_prices_json else {}
        except Exception:
            prem_prices = {"3": 143000, "6": 210000, "12": 380000}

        prem_margins = {}
        for k in ["3", "6", "12"]:
            base = prem_bases.get(k, 140000)
            curr = prem_prices.get(k, base + 5000)
            prem_margins[k] = max(0, curr - base)

        gifts = []
        try:
            gifts = json.loads(pricing.gifts_json) if pricing.gifts_json else []
        except Exception:
            gifts = []

        return {
            "stars_cost_ton": float(pricing.stars_cost_ton),
            "ton_rate_uzs": float(pricing.ton_rate_uzs),
            "margin_percent": margin,
            "fragment_stars_base_uzs": frag_star_base,
            "star_unit_price_uzs": frag_star_base,
            "unit_cost_uzs": frag_star_base,
            "unit_sell_uzs": round(unit_sell, 2),
            "discounts": discounts,
            "fragment_premium_bases": prem_bases,
            "premium_prices": prem_prices,
            "premium_margins": prem_margins,
            "gifts": gifts
        }


class PricingUpdateRequest(BaseModel):
    stars_cost_ton: float = 0.0021
    ton_rate_uzs: float = 14800.0
    margin_percent: float = 20.0
    star_unit_price_uzs: float | None = None
    discounts: list[dict[str, Any]] | None = None
    premium_prices: dict[str, Any] | None = None
    premium_margins: dict[str, Any] | None = None
    gifts: list[dict[str, Any]] | None = None


@app.post("/api/admin/pricing")
async def update_admin_pricing(req: PricingUpdateRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        disc_str = json.dumps(req.discounts) if req.discounts is not None else None
        prem_str = json.dumps(req.premium_prices) if req.premium_prices is not None else None
        gifts_str = json.dumps(req.gifts) if req.gifts is not None else None
        pricing = await queries.update_pricing(
            session=session,
            stars_cost_ton=req.stars_cost_ton,
            ton_rate_uzs=req.ton_rate_uzs,
            margin_percent=req.margin_percent,
            star_unit_price_uzs=req.star_unit_price_uzs,
            stars_discounts_json=disc_str,
            premium_prices_json=prem_str,
            gifts_json=gifts_str
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Narx sozlamalarini yangiladi",
            entity_type="pricing",
            details=f"1 Stars: {req.star_unit_price_uzs} UZS, Marja: {req.margin_percent}%"
        )
        return {"success": True, "message": "Barcha narxlar muvaffaqiyatli saqlandi!"}


@app.get("/api/admin/orders")
async def get_admin_orders(
    search: str | None = None,
    status: str | None = None,
    product_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    admin: User = Depends(require_permission(Permission.ORDERS_READ))
):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_all_orders(session, search=search, status=status, product_type=product_type, limit=limit, offset=offset)
        result = []
        for o in orders:
            u = await session.get(User, o.user_id)
            result.append({
                "id": o.id,
                "order_code": o.order_code,
                "user_id": o.user_id,
                "username": f"@{u.username}" if u and u.username else (u.first_name if u else "Noma'lum"),
                "product_type": o.product_type,
                "item_title": o.item_title,
                "amount": o.amount,
                "total_price": round(float(o.total_price)),
                "cost_price": round(float(o.cost_price)),
                "status": o.status,
                "recipient_username": o.recipient_username,
                "fulfillment_status": o.fulfillment_status or "pending",
                "fragment_payload": o.fragment_payload,
                "fragment_tx_hash": o.fragment_tx_hash,
                "fulfillment_error": o.fulfillment_error,
                "created_at": o.created_at.strftime("%d %b, %H:%M") if o.created_at else ""
            })
        return result


class OrderStatusUpdate(BaseModel):
    status: str
    reason: str | None = None


@app.post("/api/admin/orders/{order_id}/status")
async def update_order_status_endpoint(
    order_id: int,
    req: OrderStatusUpdate,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_status(
            session=session,
            order_id=order_id,
            new_status=req.status,
            admin_id=admin.id,
            reason=req.reason
        )
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

        refund_amount = float(order.total_price) if req.status in ("cancel", OrderStatus.CANCELLED, OrderStatus.REFUNDED) else 0.0
        asyncio.create_task(
            send_order_status_update_notification(
                bot=bot_instance,
                user_id=order.user_id,
                order_code=order.order_code,
                item_title=order.item_title,
                new_status=req.status,
                refund_amount=refund_amount
            )
        )
        return {"success": True, "status": order.status}


class RefundRequest(BaseModel):
    reason: str


@app.post("/api/admin/orders/{order_id}/refund")
async def refund_order_endpoint(
    order_id: int,
    req: RefundRequest,
    admin: User = Depends(require_permission(Permission.ORDERS_REFUND))
):
    """Issues an idempotent refund with traceable wallet ledger transaction and audit log."""
    async with AsyncSessionLocal() as session:
        try:
            order = await order_service.transition_order_status(
                session=session,
                order_id=order_id,
                new_status_raw=OrderStatus.REFUNDED,
                admin_id=admin.id,
                reason=req.reason
            )
            # Notify customer
            asyncio.create_task(
                send_order_status_update_notification(
                    bot=bot_instance,
                    user_id=order.user_id,
                    order_code=order.order_code,
                    item_title=order.item_title,
                    new_status="refunded",
                    refund_amount=float(order.total_price)
                )
            )
            return {"success": True, "status": order.status, "refund_amount": float(order.total_price)}
        except GiftHubException as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post("/api/admin/orders/{order_id}/retry-fulfillment")
async def retry_fulfillment_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    """Manually retries automated order fulfillment."""
    async with AsyncSessionLocal() as session:
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Yetkazib berishni qayta ishga tushirdi",
            entity_type="order",
            entity_id=str(order_id)
        )
        res = await fulfillment_service.fulfill_order_automated(session=session, order_id=order_id, bot=bot_instance)
        return res


class BalanceAdjustRequest(BaseModel):
    amount: float
    reason: str


@app.post("/api/admin/users/{user_id}/adjust-balance")
async def adjust_user_balance_endpoint(
    user_id: int,
    req: BalanceAdjustRequest,
    admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))
):
    """Manually adjusts user balance with required reason and immutable audit log."""
    async with AsyncSessionLocal() as session:
        user, tx = await wallet_service.adjust_balance_admin(
            session=session,
            admin_id=admin.id,
            user_id=user_id,
            amount=Decimal(str(req.amount)),
            reason=req.reason,
            admin_username=admin.username
        )
        await session.commit()
        return {
            "success": True,
            "user_id": user.id,
            "new_balance": float(user.balance),
            "amount_adjusted": req.amount
        }


@app.post("/api/admin/orders/{order_id}/fulfill-fragment")
async def fulfill_order_fragment_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    from app.services.fragment import fragment_client
    res = await fragment_client.fulfill_order(order_id=order_id, bot=bot_instance)
    return res


@app.post("/api/admin/orders/{order_id}/mark-fulfilled")
async def mark_order_fulfilled_endpoint(
    order_id: int,
    admin: User = Depends(require_permission(Permission.ORDERS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_fulfillment(
            session=session,
            order_id=order_id,
            fulfillment_status="fulfilled",
            status=OrderStatus.COMPLETED
        )
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Fragment yetkazishni bajarildi deb belgiladi: {order.order_code}",
            details="Admin tomonidan qo'lda tasdiqlandi"
        )
        return {"success": True, "fulfillment_status": "fulfilled"}


@app.get("/api/admin/fragment/settings")
async def get_fragment_settings_endpoint(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    from app.services.fragment import fragment_client
    async with AsyncSessionLocal() as session:
        s = await queries.get_fragment_settings(session)
        balance = await fragment_client.get_wallet_balance(s.ton_wallet_address, s.network)
        return {
            "is_auto_buy": s.is_auto_buy,
            "ton_wallet_address": s.ton_wallet_address,
            "has_mnemonic": bool(s.ton_wallet_mnemonic),
            "ton_wallet_mnemonic_masked": "••••••••••••••••••••" if s.ton_wallet_mnemonic else "",
            "tonapi_key": s.tonapi_key,
            "network": s.network,
            "min_ton_balance": float(s.min_ton_balance or 1.0),
            "simulation_mode": s.simulation_mode,
            "wallet_balance_ton": balance
        }


class FragmentSettingsUpdate(BaseModel):
    is_auto_buy: bool | None = None
    ton_wallet_address: str | None = None
    ton_wallet_mnemonic: str | None = None
    tonapi_key: str | None = None
    network: str | None = None
    min_ton_balance: float | None = None
    simulation_mode: bool | None = None


@app.post("/api/admin/fragment/settings")
async def update_fragment_settings_endpoint(
    req: FragmentSettingsUpdate,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        mnemonic = req.ton_wallet_mnemonic
        if mnemonic and "•••" in mnemonic:
            mnemonic = None

        s = await queries.update_fragment_settings(
            session=session,
            is_auto_buy=req.is_auto_buy,
            ton_wallet_address=req.ton_wallet_address,
            ton_wallet_mnemonic=mnemonic,
            tonapi_key=req.tonapi_key,
            network=req.network,
            min_ton_balance=req.min_ton_balance,
            simulation_mode=req.simulation_mode
        )
        return {"success": True, "message": "Fragment va TON sozlamalari muvaffaqiyatli saqlandi!"}


@app.get("/api/admin/users")
async def get_admin_users(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_permission(Permission.USERS_READ))
):
    async with AsyncSessionLocal() as session:
        users = await queries.list_users(session, search=search, limit=limit, offset=offset)
        from sqlalchemy import func, select
        result = []
        for u in users:
            q = await session.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(Order.user_id == u.id, Order.status.in_([OrderStatus.COMPLETED, "done"]))
            )
            count, total = q.first()
            result.append({
                "id": u.id,
                "first_name": u.first_name,
                "username": f"@{u.username}" if u.username else str(u.id),
                "role": u.role,
                "balance": round(float(u.balance)),
                "orders_count": count or 0,
                "total_spent": round(float(total or 0.0)),
                "referrals_count": u.referrals_count,
                "created_at": u.created_at.strftime("%d %b %Y") if u.created_at else ""
            })
        return result


@app.get("/api/admin/channels")
async def get_admin_channels(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    async with AsyncSessionLocal() as session:
        channels = await queries.list_channels(session, active_only=False)
        return [
            {
                "id": c.id,
                "title": c.title,
                "username_or_link": c.username_or_link,
                "req_type": c.req_type,
                "is_active": c.is_active,
                "is_detected": c.is_detected,
                "created_at": ""
            }
            for c in channels
        ]


class ChannelCreateRequest(BaseModel):
    username_or_link: str
    title: str | None = None
    req_type: str = "ordinary"
    is_detected: bool = False


@app.post("/api/admin/channels")
async def create_channel_endpoint(
    req: ChannelCreateRequest,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        link = req.username_or_link.strip()
        title = (req.title or "").strip()

        if not title and bot_instance:
            try:
                target = link
                if "t.me/" in target:
                    target = target.split("t.me/")[-1].split("/")[0].replace("+", "")
                if not target.startswith("@") and not target.startswith("-100") and not target.isdigit():
                    target = f"@{target}"
                chat = await bot_instance.get_chat(target)
                title = chat.title or chat.full_name or link
            except Exception:
                title = link
        elif not title:
            title = link

        final_req_type = req.req_type
        if final_req_type == "ordinary":
            if "/+" in link or "joinchat" in link or link.startswith("+"):
                final_req_type = "join_request"
            elif link.startswith("http") and not ("t.me/" in link or "telegram.me/" in link):
                final_req_type = "external"

        ch = await queries.add_or_update_channel(
            session=session,
            username_or_link=link,
            title=title,
            req_type=final_req_type,
            is_detected=req.is_detected
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Majburiy kanal qo'shdi/yangiladi",
            details=f"{title} ({link}, {final_req_type})"
        )
        return {"success": True, "channel_id": ch.id, "title": title, "req_type": ch.req_type}


@app.delete("/api/admin/channels/{channel_id}")
async def delete_channel_endpoint(channel_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        await queries.delete_channel(session, channel_id)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Majburiy kanalni o'chirdi (ID: {channel_id})"
        )
        return {"success": True}


@app.post("/api/admin/channels/{channel_id}/toggle")
async def toggle_channel_endpoint(channel_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await session.get(ChannelRequirement, channel_id)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        ch.is_active = not ch.is_active
        await session.commit()
        return {"success": True, "is_active": ch.is_active}


class ChannelConfirmRequest(BaseModel):
    req_type: str = "ordinary"


@app.post("/api/admin/channels/{channel_id}/confirm")
async def confirm_channel_endpoint(channel_id: int, req: ChannelConfirmRequest, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await queries.confirm_detected_channel(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}


class ChannelTypeUpdateRequest(BaseModel):
    req_type: str


@app.post("/api/admin/channels/{channel_id}/type")
async def update_channel_type_endpoint(channel_id: int, req: ChannelTypeUpdateRequest, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ch = await queries.update_channel_type(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}


# ================= ADMIN PROMOCODES ================= #

@app.get("/api/admin/promocodes")
async def get_admin_promocodes(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        promos = await queries.list_promo_codes(session)
        return [
            {
                "id": p.id,
                "code": p.code,
                "reward_type": p.reward_type,
                "reward_value": float(p.reward_value),
                "max_uses": p.max_uses,
                "current_uses": p.current_uses,
                "min_order_amount": float(p.min_order_amount),
                "is_active": p.is_active,
                "created_at": p.created_at.strftime("%d %b %Y") if p.created_at else ""
            }
            for p in promos
        ]


class PromoCreateRequest(BaseModel):
    code: str
    reward_type: str = "discount_percent"
    reward_value: float = 10.0
    max_uses: int = 100
    min_order_amount: float = 0.0
    is_active: bool = True


@app.post("/api/admin/promocodes")
async def create_admin_promocode(req: PromoCreateRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        try:
            promo = await queries.create_promo_code(
                session=session,
                code=req.code,
                reward_type=req.reward_type,
                reward_value=req.reward_value,
                max_uses=req.max_uses,
                min_order_amount=req.min_order_amount,
                is_active=req.is_active
            )
            await queries.log_admin_action(
                session=session,
                admin_id=admin.id,
                admin_username=admin.username,
                action="Yangi promo-kod yaratdi",
                entity_type="promo",
                entity_id=str(promo.id),
                details=f"{promo.code} ({promo.reward_type}: {promo.reward_value})"
            )
            return {"success": True, "promo_id": promo.id}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/admin/promocodes/{promo_id}")
async def delete_admin_promocode(promo_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        deleted = await queries.delete_promo_code(session, promo_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        return {"success": True}


@app.post("/api/admin/promocodes/{promo_id}/toggle")
async def toggle_admin_promocode(promo_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        promo = await queries.toggle_promo_code(session, promo_id)
        if not promo:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        return {"success": True, "is_active": promo.is_active}


# ================= ADMIN PAYMENT SETTINGS ================= #

@app.get("/api/admin/payments")
async def get_payment_settings_endpoint(admin: User = Depends(require_permission(Permission.PAYMENTS_READ))):
    async with AsyncSessionLocal() as session:
        p = await session.get(PaymentSetting, 1)
        return {
            "click_active": p.click_active if p else True,
            "payme_active": p.payme_active if p else True,
            "card_active": getattr(p, "card_active", True) if p else True,
            "card_number": getattr(p, "card_number", "8600 1234 5678 9012") if p else "8600 1234 5678 9012",
            "card_holder": getattr(p, "card_holder", "ANVAR S.") if p else "ANVAR S.",
            "bank_name": getattr(p, "bank_name", "TBC Bank") if p else "TBC Bank",
            "autopaycard_active": p.autopaycard_active if p else False,
            "autopaycard_last4": p.autopaycard_last4 if p else "6412",
            "autopaycard_email": p.autopaycard_email if p else "payments.gifthub@gmail.com",
            "autopaycard_webhook_url": p.autopaycard_webhook_url if p else "https://gifthub.uz/webhook/autopaycard"
        }


class PaymentSettingsUpdate(BaseModel):
    click_active: bool = True
    payme_active: bool = True
    card_active: bool = True
    card_number: str | None = "8600 1234 5678 9012"
    card_holder: str | None = "ANVAR S."
    bank_name: str | None = "TBC Bank"
    autopaycard_active: bool = False
    autopaycard_api_key: str | None = None
    autopaycard_last4: str | None = None
    autopaycard_email: str | None = None


@app.post("/api/admin/payments")
async def update_payment_settings_endpoint(
    req: PaymentSettingsUpdate,
    admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))
):
    async with AsyncSessionLocal() as session:
        p = await session.get(PaymentSetting, 1)
        if not p:
            p = PaymentSetting(id=1)
            session.add(p)
        p.click_active = req.click_active
        p.payme_active = req.payme_active
        p.card_active = req.card_active
        if req.card_number is not None:
            p.card_number = req.card_number.strip()
        if req.card_holder is not None:
            p.card_holder = req.card_holder.strip()
        if req.bank_name is not None:
            p.bank_name = req.bank_name.strip()
        p.autopaycard_active = req.autopaycard_active
        if req.autopaycard_api_key is not None:
            p.autopaycard_api_key = req.autopaycard_api_key
        if req.autopaycard_last4 is not None:
            p.autopaycard_last4 = req.autopaycard_last4
        if req.autopaycard_email is not None:
            p.autopaycard_email = req.autopaycard_email
        await session.commit()
        return {"success": True}


class PaymentCardCreate(BaseModel):
    card_number: str
    card_holder: str
    bank_name: str
    card_type: str = "UZCARD"
    is_active: bool = True


class PaymentCardUpdate(BaseModel):
    card_number: str | None = None
    card_holder: str | None = None
    bank_name: str | None = None
    card_type: str | None = None
    is_active: bool | None = None


@app.get("/api/admin/cards")
async def get_admin_cards_endpoint(admin: User = Depends(require_permission(Permission.PAYMENTS_READ))):
    async with AsyncSessionLocal() as session:
        cards = await queries.list_payment_cards(session)
        return [
            {
                "id": c.id,
                "card_number": c.card_number,
                "card_holder": c.card_holder,
                "bank_name": c.bank_name,
                "card_type": c.card_type,
                "is_active": c.is_active,
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
            }
            for c in cards
        ]


@app.post("/api/admin/cards")
async def create_admin_card_endpoint(req: PaymentCardCreate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        c = await queries.create_payment_card(
            session=session,
            card_number=req.card_number,
            card_holder=req.card_holder,
            bank_name=req.bank_name,
            card_type=req.card_type,
            is_active=req.is_active
        )
        return {"success": True, "id": c.id}


@app.put("/api/admin/cards/{card_id}")
async def update_admin_card_endpoint(card_id: int, req: PaymentCardUpdate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        c = await queries.update_payment_card(
            session=session,
            card_id=card_id,
            card_number=req.card_number,
            card_holder=req.card_holder,
            bank_name=req.bank_name,
            card_type=req.card_type,
            is_active=req.is_active
        )
        if not c:
            raise HTTPException(status_code=404, detail="Karta topilmadi")
        return {"success": True}


@app.delete("/api/admin/cards/{card_id}")
async def delete_admin_card_endpoint(card_id: int, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_payment_card(session, card_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Karta topilmadi")
        return {"success": True}


@app.get("/api/admin/referral")
async def get_referral_settings_endpoint(admin: User = Depends(require_permission(Permission.SETTINGS_READ))):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        return {
            "bonus_percent": float(r.bonus_percent) if r else 5.0,
            "min_purchase_uzs": float(r.min_purchase_uzs) if r else 20000.0,
            "auto_reward": r.auto_reward if r else True,
            "require_purchase": r.require_purchase if r else True
        }


class ReferralSettingsUpdate(BaseModel):
    bonus_percent: float
    min_purchase_uzs: float
    auto_reward: bool
    require_purchase: bool


@app.post("/api/admin/referral")
async def update_referral_settings_endpoint(req: ReferralSettingsUpdate, admin: User = Depends(require_permission(Permission.SETTINGS_UPDATE))):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        if not r:
            r = ReferralSetting(id=1)
            session.add(r)
        r.bonus_percent = Decimal(str(req.bonus_percent))
        r.min_purchase_uzs = Decimal(str(req.min_purchase_uzs))
        r.auto_reward = req.auto_reward
        r.require_purchase = req.require_purchase
        await session.commit()
        return {"success": True}


@app.get("/api/admin/admins")
async def get_admins_list(admin: User = Depends(require_permission(Permission.ADMINS_READ))):
    async with AsyncSessionLocal() as session:
        admins = await queries.list_admins(session)
        return [
            {
                "id": a.id,
                "first_name": a.first_name,
                "username": f"@{a.username}" if a.username else str(a.id),
                "role": a.role,
                "created_at": a.created_at.strftime("%d %b %Y") if a.created_at else ""
            }
            for a in admins
        ]


class AddAdminRequest(BaseModel):
    identifier: str
    role: str


@app.post("/api/admin/admins")
async def add_admin_endpoint(req: AddAdminRequest, admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))):
    async with AsyncSessionLocal() as session:
        target_user = None
        ident = req.identifier.strip()
        if ident.isdigit():
            target_user = await queries.get_user_by_id(session, int(ident))
        else:
            target_user = await queries.get_user_by_username(session, ident)

        if not target_user:
            raise HTTPException(status_code=404, detail=f"Foydalanuvchi topilmadi: {ident}")

        updated = await queries.set_user_role(session, target_user.id, req.role)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Yangi admin tayinladi: @{updated.username or updated.id}",
            entity_type="admin",
            entity_id=str(updated.id),
            details=f"Rol: {req.role}"
        )
        return {"success": True, "message": f"@{updated.username or updated.id} ga '{req.role}' roli berildi!"}


@app.delete("/api/admin/admins/{user_id}")
async def revoke_admin_endpoint(user_id: int, admin: User = Depends(require_permission(Permission.ADMINS_MANAGE))):
    async with AsyncSessionLocal() as session:
        if user_id in settings.ADMINS and admin.id != user_id:
            raise HTTPException(status_code=400, detail="Bosh adminni olib tashlab bo'lmaydi!")
        await queries.set_user_role(session, user_id, "user")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Admin huquqini bekor qildi: ID {user_id}",
            entity_type="admin",
            entity_id=str(user_id)
        )
        return {"success": True}


@app.get("/api/admin/audit-logs")
async def get_audit_logs(admin: User = Depends(require_permission(Permission.ADMINS_READ))):
    async with AsyncSessionLocal() as session:
        logs = await queries.list_audit_logs(session, limit=50)
        return [
            {
                "id": log_item.id,
                "admin": f"@{log_item.admin_username}" if log_item.admin_username else f"ID {log_item.admin_id}",
                "action": log_item.action,
                "entity_type": log_item.entity_type,
                "details": log_item.details,
                "created_at": log_item.created_at.strftime("%d %b, %H:%M") if log_item.created_at else ""
            }
            for log_item in logs
        ]


# ================= ADMIN SUPPORT TICKETS ================= #

@app.get("/api/admin/support/tickets")
async def list_admin_support_tickets(
    status: str | None = None,
    limit: int = 50,
    admin: User = Depends(require_permission(Permission.SUPPORT_READ))
):
    async with AsyncSessionLocal() as session:
        tickets = await support_service.list_all_tickets(session, status=status, limit=limit)
        return [
            {
                "id": t.id,
                "user_id": t.user_id,
                "subject": t.subject,
                "category": t.category,
                "status": t.status,
                "order_id": t.order_id,
                "assigned_admin_id": t.assigned_admin_id,
                "created_at": t.created_at.strftime("%d %b, %H:%M") if t.created_at else "",
                "updated_at": t.updated_at.strftime("%d %b, %H:%M") if t.updated_at else ""
            }
            for t in tickets
        ]


class AdminTicketStatusUpdate(BaseModel):
    status: str


@app.post("/api/admin/support/tickets/{ticket_id}/status")
async def update_admin_ticket_status(
    ticket_id: int,
    req: AdminTicketStatusUpdate,
    admin: User = Depends(require_permission(Permission.SUPPORT_REPLY))
):
    async with AsyncSessionLocal() as session:
        ticket = await support_service.update_status(
            session=session,
            ticket_id=ticket_id,
            status=req.status,
            assigned_admin_id=admin.id
        )
        return {"success": True, "status": ticket.status}


# ================= BROADCAST ENDPOINTS ================= #

class BroadcastRequest(BaseModel):
    segment: str = "all"
    mode: str = "write"
    text: str | None = None
    photo_url: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    buttons: list[dict[str, str]] | None = None
    post_link: str | None = None
    forward_mode: bool = False
    postbot_code: str | None = None
    draft_id: int | None = None


latest_broadcast_status = {
    "is_running": False,
    "total": 0,
    "sent": 0,
    "blocked": 0,
    "failed": 0,
    "completed_at": None
}


@app.get("/api/admin/broadcast/status")
async def get_broadcast_status(admin: User = Depends(require_permission(Permission.BROADCAST_CREATE))):
    return latest_broadcast_status


@app.get("/api/admin/broadcast/latest-draft")
async def get_latest_broadcast_draft_endpoint(admin: User = Depends(require_permission(Permission.BROADCAST_CREATE))):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(BroadcastDraft).order_by(BroadcastDraft.id.desc()).limit(1))
        d = res.scalars().first()
        if not d:
            return {"has_draft": False}
        return {
            "has_draft": True,
            "draft": {
                "id": d.id,
                "mode": d.mode,
                "text": d.text,
                "photo": d.photo,
                "button_text": d.button_text,
                "button_url": d.button_url,
                "forward_chat_id": d.forward_chat_id,
                "forward_message_id": d.forward_message_id,
                "created_at": d.created_at.strftime("%d %b, %H:%M") if d.created_at else ""
            }
        }


@app.post("/api/admin/broadcast")
async def send_broadcast_endpoint(req: BroadcastRequest, admin: User = Depends(require_permission(Permission.BROADCAST_SEND))):
    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session, req.segment)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Broadcast boshlandi: {len(recipients)} ta foydalanuvchiga",
            entity_type="broadcast",
            details=f"Segment: {req.segment}, Rejim: {req.mode}"
        )
        asyncio.create_task(run_broadcast_queue(recipients, req, admin_id=admin.id))
        return {
            "success": True,
            "recipients_count": len(recipients),
            "message": f"Broadcast {len(recipients)} ta foydalanuvchiga yuborilmoqda..."
        }


async def run_broadcast_queue(recipients: list[int], req: BroadcastRequest, admin_id: int | None = None):
    global latest_broadcast_status
    if not bot_instance:
        return

    latest_broadcast_status = {
        "is_running": True,
        "total": len(recipients),
        "sent": 0,
        "blocked": 0,
        "failed": 0,
        "completed_at": None
    }

    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    inline_keyboard = []
    if req.buttons:
        for b in req.buttons:
            t = (b.get("text") or "").strip()
            u = (b.get("url") or "").strip()
            if t and u and (u.startswith("https://") or u.startswith("http://") or u.startswith("tg://")):
                inline_keyboard.append([InlineKeyboardButton(text=t, url=u)])
    elif req.button_text:
        b_url = req.button_url or settings.WEB_APP_URL
        if b_url.startswith("https://") or b_url.startswith("http://"):
            inline_keyboard.append([InlineKeyboardButton(text=req.button_text, url=b_url)])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard) if inline_keyboard else None

    post_info = None
    if req.post_link:
        try:
            clean_link = req.post_link.strip().rstrip("/")
            parts = clean_link.split("/")
            if len(parts) >= 2:
                msg_id = int(parts[-1])
                chat_id_or_user = parts[-2]
                if chat_id_or_user == "c" and len(parts) >= 3:
                    chat_ref = int("-100" + parts[-3])
                elif chat_id_or_user.isdigit() or chat_id_or_user.startswith("-"):
                    chat_ref = int(chat_id_or_user)
                else:
                    chat_ref = f"@{chat_id_or_user}" if not chat_id_or_user.startswith("@") else chat_id_or_user
                post_info = (chat_ref, msg_id)
        except Exception as e:
            logger.warning(f"Broadcast post link parse error: {e}")

    for uid in recipients:
        try:
            if post_info:
                chat_ref, msg_id = post_info
                if req.forward_mode:
                    await bot_instance.forward_message(chat_id=uid, from_chat_id=chat_ref, message_id=msg_id)
                else:
                    await bot_instance.copy_message(chat_id=uid, from_chat_id=chat_ref, message_id=msg_id, reply_markup=reply_markup)
            elif req.photo_url and req.photo_url.startswith("http"):
                await bot_instance.send_photo(chat_id=uid, photo=req.photo_url, caption=req.text or "", reply_markup=reply_markup)
            elif req.text:
                await bot_instance.send_message(chat_id=uid, text=req.text, reply_markup=reply_markup)
            latest_broadcast_status["sent"] += 1
            await asyncio.sleep(0.04) # ~25-30 msgs/sec
        except TelegramForbiddenError:
            latest_broadcast_status["blocked"] += 1
        except Exception:
            latest_broadcast_status["failed"] += 1

    latest_broadcast_status["is_running"] = False
    latest_broadcast_status["completed_at"] = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M")

    if admin_id and bot_instance:
        report = (
            f"📢 <b>GiftHub Broadcast yakunlandi!</b>\n\n"
            f"👥 Jami: {latest_broadcast_status['total']}\n"
            f"✅ Yetkazildi: {latest_broadcast_status['sent']}\n"
            f"🚫 Bloklagan: {latest_broadcast_status['blocked']}\n"
            f"⚠️ Xatolar: {latest_broadcast_status['failed']}\n"
            f"⏱ Vaqt: {latest_broadcast_status['completed_at']}"
        )
        try:
            await bot_instance.send_message(chat_id=admin_id, text=report)
        except Exception:
            pass


@app.get("/api/admin/export/orders.csv")
async def export_orders_csv(admin: User = Depends(require_permission(Permission.ORDERS_READ))):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_all_orders(session, limit=1000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Buyurtma kodi", "User ID", "Mahsulot", "Miqdor", "Summa (UZS)", "Tannarx (UZS)", "Holat", "Sana"])
        for o in orders:
            writer.writerow([
                o.id,
                o.order_code,
                o.user_id,
                o.item_title,
                o.amount,
                round(float(o.total_price)),
                round(float(o.cost_price)),
                o.status,
                o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""
            ])
        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=gifthub_orders.csv"}
        )


# ================= CUSTOM SERVICES API ================= #

class CreateServiceRequest(BaseModel):
    name: str
    price_uzs: float
    cost_uzs: float = 0.0
    category: str = "Xizmatlar"
    icon: str = "⚡"
    description: str = ""
    is_active: bool = True


class UpdateServiceRequest(BaseModel):
    name: str | None = None
    price_uzs: float | None = None
    cost_uzs: float | None = None
    category: str | None = None
    icon: str | None = None
    description: str | None = None
    is_active: bool | None = None


@app.get("/api/admin/services")
async def api_admin_list_services(admin: User = Depends(require_permission(Permission.PRICING_READ))):
    async with AsyncSessionLocal() as session:
        services = await queries.list_custom_services(session=session, active_only=False)
        return [
            {
                "id": s.id,
                "name": s.name,
                "price_uzs": float(s.price_uzs),
                "cost_uzs": float(s.cost_uzs),
                "category": s.category,
                "icon": s.icon,
                "description": s.description,
                "is_active": s.is_active,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""
            }
            for s in services
        ]


@app.post("/api/admin/services")
async def api_admin_create_service(req: CreateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Xizmat nomi kiritilishi shart")
    async with AsyncSessionLocal() as session:
        s = await queries.create_custom_service(
            session=session,
            name=req.name,
            price_uzs=req.price_uzs,
            cost_uzs=req.cost_uzs,
            category=req.category,
            icon=req.icon,
            description=req.description,
            is_active=req.is_active
        )
        return {"success": True, "id": s.id, "message": "Xizmat muvaffaqiyatli qo'shildi"}


@app.put("/api/admin/services/{service_id}")
async def api_admin_update_service(service_id: int, req: UpdateServiceRequest, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        s = await queries.update_custom_service(
            session=session,
            service_id=service_id,
            name=req.name,
            price_uzs=req.price_uzs,
            cost_uzs=req.cost_uzs,
            category=req.category,
            icon=req.icon,
            description=req.description,
            is_active=req.is_active
        )
        if not s:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat muvaffaqiyatli yangilandi"}


@app.delete("/api/admin/services/{service_id}")
async def api_admin_delete_service(service_id: int, admin: User = Depends(require_permission(Permission.PRICING_UPDATE))):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_custom_service(session=session, service_id=service_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat o'chirildi"}


# ================= FRONTEND MOUNTING ================= #

@app.get("/app", response_class=HTMLResponse)
async def serve_user_app():
    user_app_path = os.path.join(settings.BASE_DIR, "web", "user", "index.html")
    if os.path.exists(user_app_path):
        with open(user_app_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h2>GiftHub Web App fayli topilmadi.</h2>", status_code=404)


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_app():
    admin_app_path = os.path.join(settings.BASE_DIR, "web", "admin", "index.html")
    if os.path.exists(admin_app_path):
        with open(admin_app_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h2>GiftHub Admin Panel fayli topilmadi.</h2>", status_code=404)


@app.get("/")
async def root_redirect():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="uz">
      <head>
        <meta charset="UTF-8">
        <title>GiftHub — Digital Commerce Platform</title>
        <style>
          body { background:#080C0A; color:#EFFBF4; font-family:-apple-system,BlinkMacSystemFont,sans-serif; text-align:center; padding:60px 20px; }
          .card { max-width:480px; margin:0 auto; background:#121A16; border:1px solid #22302A; border-radius:20px; padding:40px 30px; }
          h1 { color:#12E88B; margin-bottom:10px; font-size:28px; }
          p { color:#8AA69A; font-size:15px; margin-bottom:30px; }
          .btn { display:inline-block; padding:12px 24px; border-radius:12px; font-weight:600; text-decoration:none; margin:8px; font-size:14px; }
          .btn-primary { background:#12E88B; color:#0A100D; }
          .btn-secondary { background:#1D2A24; color:#BFFFDD; border:1px solid #2A3C34; }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>⭐ GiftHub</h1>
          <p>Telegram Stars, Premium obuna va Raqamli sovg'alar platformasi</p>
          <div>
            <a href="/app" class="btn btn-primary">Foydalanuvchi Do'koni (Web App)</a>
            <a href="/admin" class="btn btn-secondary">Admin Boshqaruv Paneli</a>
          </div>
        </div>
      </body>
    </html>
    """)
