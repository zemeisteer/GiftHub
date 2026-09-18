import os
import json
import csv
import io
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data import config
from database.db import AsyncSessionLocal
from database.models import (
    User, PricingSetting, Order, Transaction, ChannelRequirement,
    AdminAuditLog, ReferralSetting, PaymentSetting, BroadcastDraft
)
from database import queries
from app.web.auth import validate_init_data
from app.utils.notifications import (
    send_topup_notification,
    send_order_created_notification,
    send_admin_order_alert,
    send_order_status_update_notification,
    send_referral_reward_notification,
    send_promocode_notification
)
from app.web.payments import (
    generate_click_link, process_click_prepare, process_click_complete,
    generate_payme_link, handle_payme_request, verify_payme_auth,
    handle_autopaycard_webhook
)

app = FastAPI(title="Stellar Bot Web App & API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reference to the running bot instance (set during startup in main.py)
bot_instance = None
bot_username = None

def set_bot(bot, username: Optional[str] = None):
    global bot_instance, bot_username
    bot_instance = bot
    if username:
        bot_username = username

@app.get("/api/bot-info")
async def get_bot_info():
    uname = bot_username
    if not uname and bot_instance:
        try:
            me = await bot_instance.get_me()
            uname = me.username
        except Exception:
            pass
    return {"username": uname or "stellar_gift_bot"}

# ================= AUTH HELPER ================= #

async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(None),
    x_auth_user_id: Optional[str] = Header(None),
    auth_user_id: Optional[int] = Query(None)
) -> User:
    """
    Authenticates user via Telegram WebApp initData header or dev auth_user_id.
    """
    async with AsyncSessionLocal() as session:
        if x_telegram_init_data:
            tg_user = validate_init_data(x_telegram_init_data)
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
                logging.warning(f"⚠️ Telegram initData haqiqiy emas yoki tekshiruvdan o'tmadi!")

        # Explicit test / development user ID from query or custom header
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

        # Standalone browser demo (when opened directly in browser without Telegram)
        # Never impersonate real admin user for normal users!
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

async def get_current_admin(
    x_telegram_init_data: Optional[str] = Header(None),
    x_auth_user_id: Optional[str] = Header(None),
    auth_user_id: Optional[int] = Query(None)
) -> User:
    async with AsyncSessionLocal() as session:
        if x_telegram_init_data:
            tg_user = validate_init_data(x_telegram_init_data)
            if tg_user and "id" in tg_user:
                user = await queries.get_or_create_user(
                    session=session,
                    user_id=int(tg_user["id"]),
                    first_name=tg_user.get("first_name", "Foydalanuvchi"),
                    last_name=tg_user.get("last_name"),
                    username=tg_user.get("username"),
                    photo_url=tg_user.get("photo_url")
                )
                if user.role == "user" and str(user.id) not in config.ADMINS:
                    raise HTTPException(status_code=403, detail="Ruxsat berilmagan: Siz admin emassiz!")
                return user

        effective_uid = auth_user_id
        if not effective_uid and x_auth_user_id and x_auth_user_id.isdigit():
            effective_uid = int(x_auth_user_id)

        if effective_uid:
            user = await queries.get_user_by_id(session, effective_uid)
            if user and (user.role != "user" or str(user.id) in config.ADMINS):
                return user
            raise HTTPException(status_code=403, detail="Ruxsat berilmagan: Siz admin emassiz!")

        # Standalone PC browser access for Admin Panel (development / server manager)
        if config.ADMINS:
            admin_uid = int(config.ADMINS[0])
            admin_user = await queries.get_user_by_id(session, admin_uid)
            if admin_user:
                return admin_user
            return await queries.get_or_create_user(
                session=session,
                user_id=admin_uid,
                first_name="Admin",
                username="admin"
            )

        raise HTTPException(status_code=403, detail="Ruxsat berilmagan: Admin mavjud emas!")

# ================= USER API ROUTES ================= #

@app.get("/api/user/me")
async def get_me(user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select, func
        # Count total orders
        res = await session.execute(
            select(func.count(Order.id)).where(Order.user_id == user.id)
        )
        orders_count = res.scalar() or 0

        # Count completed orders
        res_done = await session.execute(
            select(func.count(Order.id)).where(Order.user_id == user.id, Order.status == "done")
        )
        completed_orders = res_done.scalar() or 0

        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "photo_url": user.photo_url,
            "balance": round(user.balance),
            "role": user.role,
            "referrals_count": user.referrals_count,
            "referral_earnings": round(user.referral_earnings),
            "orders_count": orders_count,
            "completed_orders": completed_orders,
            "created_at": user.created_at.strftime("%d %b %Y") if user.created_at else ""
        }

@app.get("/api/gate/check")
async def check_gate_channels(user: User = Depends(get_current_user)):
    """
    Checks mandatory subscription conditions (gate screen).
    Supports: ordinary, join_request, external.
    """
    async with AsyncSessionLocal() as session:
        # Admins bypass gate screen
        if str(user.id) in config.ADMINS or (user.role and user.role != "user"):
            return {
                "all_passed": True,
                "channels": []
            }

        channels = await queries.list_channels(session, active_only=True)
        results = []
        all_passed = True

        for ch in channels:
            if ch.is_detected:
                continue

            is_member = False
            if ch.req_type == "external":
                # External links cannot be checked by bot API; marked as soft requirement
                is_member = True
            elif ch.req_type == "join_request":
                # Check if user sent join request or is already an accepted member
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
                # Ordinary / Group channel
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

        return {
            "all_passed": all_passed,
            "channels": results
        }

@app.get("/api/products")
async def get_products(stars_amount: Optional[int] = None):
    """
    Returns calculated product packages for Stars, Premium, and Gifts based on pricing engine.
    """
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)

        # Calculate popular Stars packages
        popular_amounts = [50, 100, 250, 500, 1000]
        stars_packages = []
        for amt in popular_amounts:
            calc = queries.calculate_stars_price(amt, pricing)
            stars_packages.append({
                "amount": amt,
                "name": f"{amt} ⭐",
                "price_uzs": calc["total_price_uzs"],
                "discount_pct": calc["discount_percent"],
                "formatted_price": f"{calc['total_price_uzs']:,}".replace(",", " ") + " so'm"
            })

        custom_calc = None
        if stars_amount and stars_amount > 0:
            custom_calc = queries.calculate_stars_price(stars_amount, pricing)

        # Premium packages
        try:
            prem_data = json.loads(pricing.premium_prices_json)
        except Exception:
            prem_data = {"3": 142000, "6": 210000, "12": 380000}

        premium_packages = [
            {"months": 3, "name": "Premium — 3 oy", "price_uzs": prem_data.get("3", 142000), "icon": "💎"},
            {"months": 6, "name": "Premium — 6 oy", "price_uzs": prem_data.get("6", 210000), "icon": "💎"},
            {"months": 12, "name": "Premium — 12 oy", "price_uzs": prem_data.get("12", 380000), "icon": "👑"}
        ]

        # Gifts list
        try:
            gifts_list = json.loads(pricing.gifts_json)
        except Exception:
            gifts_list = [
                {"id": "bear", "name": "Teddy Bear sovg'a", "price_uzs": 64000, "icon": "🧸"},
                {"id": "heart", "name": "Neon Heart sovg'a", "price_uzs": 85000, "icon": "💖"},
                {"id": "rocket", "name": "Cosmo Rocket sovg'a", "price_uzs": 120000, "icon": "🚀"}
            ]

        # Active payment methods
        payment_setting = await session.get(PaymentSetting, 1)
        payment_methods = []
        card_info = None
        if payment_setting:
            if getattr(payment_setting, "card_active", True):
                c_num = getattr(payment_setting, "card_number", "8600 1234 5678 9012")
                c_holder = getattr(payment_setting, "card_holder", "ANVAR S.")
                b_name = getattr(payment_setting, "bank_name", "TBC Bank")
                card_info = {
                    "card_number": c_num,
                    "card_holder": c_holder,
                    "bank_name": b_name
                }
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

        from app.services.fragment import pricing_engine
        star_base_cost = pricing_engine.get_fragment_star_base_uzs()
        margin = pricing.margin_percent if pricing and pricing.margin_percent is not None else 20.0
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
    if req.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimal to'ldirish summasi: 1 000 so'm")

    async with AsyncSessionLocal() as session:
        # In test / demo environment or payment gateway checkout:
        # We credit balance immediately and record transaction
        updated_user = await queries.update_user_balance(
            session=session,
            user_id=user.id,
            amount=req.amount,
            tx_type="topup",
            method=req.method,
            note=f"{req.method.upper()} orqali hamyon to'ldirildi"
        )

        # Asynchronously send notification to user via bot
        asyncio.create_task(
            send_topup_notification(
                bot=bot_instance,
                user_id=user.id,
                amount=req.amount,
                method=req.method,
                new_balance=updated_user.balance
            )
        )

        return {
            "success": True,
            "new_balance": round(updated_user.balance),
            "amount": req.amount,
            "method": req.method,
            "message": f"Hamyon muvaffaqiyatli to'ldirildi! (+{req.amount:,.0f} so'm)"
        }

class CheckoutLinkRequest(BaseModel):
    amount: float
    method: str # click, payme, autopaycard

@app.post("/api/wallet/checkout-link")
async def get_checkout_link(req: CheckoutLinkRequest, user: User = Depends(get_current_user)):
    if req.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimal to'ldirish summasi: 1 000 so'm")

    if req.method == "click":
        url = generate_click_link(user.id, req.amount)
        return {"success": True, "method": "click", "checkout_url": url, "amount": req.amount}
    elif req.method == "payme":
        url = generate_payme_link(user.id, req.amount)
        return {"success": True, "method": "payme", "checkout_url": url, "amount": req.amount}
    elif req.method == "autopaycard":
        async with AsyncSessionLocal() as session:
            ps = await session.get(PaymentSetting, 1)
            card_last4 = ps.autopaycard_last4 if ps else "6412"
            return {
                "success": True,
                "method": "autopaycard",
                "instructions": f"Ushbu summani ko'rsatilgan Uzcard kartaga o'tkazing: **** **** **** {card_last4}",
                "amount": req.amount
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
            "error": {
                "code": -32504,
                "message": "Avtorizatsiya xatosi"
            }
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


class PurchaseRequest(BaseModel):
    product_type: str # stars, premium, gift
    item_title: str
    amount: int = 1
    total_price: float
    recipient_username: Optional[str] = None

@app.post("/api/orders/create")
async def create_order_endpoint(req: PurchaseRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        # Fetch fresh user to check balance
        u = await queries.get_user_by_id(session, user.id)
        if not u or u.balance < req.total_price:
            raise HTTPException(
                status_code=400,
                detail=f"Balansingizda mablag' yetarli emas! Joriy balans: {round(u.balance if u else 0):,} so'm"
            )

        pricing = await queries.get_pricing(session)
        cost_price = req.total_price * 0.85 # default approx cost

        if req.product_type == "stars":
            calc = queries.calculate_stars_price(req.amount, pricing)
            cost_price = calc["cost_total_uzs"]
        elif req.product_type == "premium":
            prem_base = {"3": 138000, "6": 205000, "12": 375000}
            cost_price = prem_base.get(str(req.amount), req.total_price * 0.9)

        order, bonus, referrer = await queries.create_order(
            session=session,
            user_id=user.id,
            product_type=req.product_type,
            item_title=req.item_title,
            amount=req.amount,
            total_price=req.total_price,
            cost_price=cost_price,
            recipient_username=req.recipient_username
        )

        # Trigger Fragment automated purchase & delivery
        from app.services.fragment import fragment_client
        asyncio.create_task(
            fragment_client.fulfill_order(order_id=order.id, bot=bot_instance)
        )

        # Trigger background notifications
        asyncio.create_task(
            send_order_created_notification(
                bot=bot_instance,
                user_id=user.id,
                order_code=order.order_code,
                item_title=order.item_title,
                amount=order.amount,
                total_price=order.total_price,
                status=order.status,
                new_balance=u.balance - req.total_price,
                recipient_username=req.recipient_username,
                buyer_username=user.username
            )
        )
        asyncio.create_task(
            send_admin_order_alert(
                bot=bot_instance,
                admin_ids=config.ADMINS,
                user_name=user.first_name,
                user_id=user.id,
                username=user.username,
                order_code=order.order_code,
                item_title=order.item_title,
                amount=order.amount,
                total_price=order.total_price,
                cost_price=cost_price,
                status=order.status,
                recipient_username=req.recipient_username
            )
        )
        if bonus > 0 and referrer:
            asyncio.create_task(
                send_referral_reward_notification(
                    bot=bot_instance,
                    referrer_id=referrer.id,
                    buyer_name=user.first_name,
                    bonus_amount=bonus,
                    new_balance=referrer.balance
                )
            )

        return {
            "success": True,
            "order_code": order.order_code,
            "new_balance": round(u.balance - req.total_price),
            "status": order.status,
            "message": f"{req.item_title} muvaffaqiyatli xarid qilindi!"
        }

@app.get("/api/orders/history")
async def get_order_history(
    status: Optional[str] = "all",
    user: User = Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_user_orders(session, user_id=user.id, status=status)
        return [
            {
                "id": o.id,
                "order_code": o.order_code,
                "product_type": o.product_type,
                "item_title": o.item_title,
                "amount": o.amount,
                "total_price": round(o.total_price),
                "formatted_price": f"{round(o.total_price):,} so'm".replace(",", " "),
                "status": o.status,
                "created_at": o.created_at.strftime("%d %b, %H:%M") if o.created_at else ""
            }
            for o in orders
        ]

class PromoApplyRequest(BaseModel):
    code: str
    order_total: Optional[float] = 0.0

@app.post("/api/promocodes/apply")
async def apply_promocode_endpoint(req: PromoApplyRequest, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await queries.apply_promo_code(
            session=session,
            code=req.code,
            user_id=user.id,
            order_total=req.order_total
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["detail"])

        # Send Telegram notification via bot
        asyncio.create_task(
            send_promocode_notification(
                bot=bot_instance,
                user_id=user.id,
                code=req.code,
                message=result.get("message", "Muvaffaqiyatli qo'llandi!"),
                new_balance=result.get("new_balance")
            )
        )
        return result

# ================= ADMIN API ROUTES ================= #

@app.get("/api/admin/dashboard")
async def get_admin_dashboard(admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select, func
        # New users count
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        users_total = (await session.execute(select(func.count(User.id)))).scalar() or 0
        new_users_week = (await session.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )).scalar() or 0

        # Total sales & profit
        sales_total = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.status == "done")
        )).scalar() or 0.0

        cost_total = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.status == "done")
        )).scalar() or 0.0

        profit_total = sales_total - cost_total

        # Referrals sales count
        ref_sales_count = (await session.execute(
            select(func.count(Order.id)).join(User, Order.user_id == User.id).where(
                User.referrer_id.isnot(None), Order.status == "done"
            )
        )).scalar() or 0

        # Product sales breakdown
        stars_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "stars", Order.status == "done")
        )).scalar() or 0.0
        stars_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "stars", Order.status == "done")
        )).scalar() or 0.0

        prem_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "premium", Order.status == "done")
        )).scalar() or 0.0
        prem_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "premium", Order.status == "done")
        )).scalar() or 0.0

        gifts_sales = (await session.execute(
            select(func.sum(Order.total_price)).where(Order.product_type == "gift", Order.status == "done")
        )).scalar() or 0.0
        gifts_cost = (await session.execute(
            select(func.sum(Order.cost_price)).where(Order.product_type == "gift", Order.status == "done")
        )).scalar() or 0.0

        # Fetch completed orders for sales charts (last 30 days)
        month_ago = now - timedelta(days=30)
        orders_q = await session.execute(
            select(Order.total_price, Order.created_at, Order.completed_at)
            .where(Order.status == "done", Order.created_at >= month_ago)
        )
        done_orders = orders_q.all()

        # 1. Kunlik (Bugungi kun - 4 soatlik intervallar)
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
                        slot["sales"] += round(row.total_price or 0)
                        slot["count"] += 1
                        break

        # 2. Haftalik (So'nggi 7 kun: Du, Se, Ch, Pa, Ju, Sh, Ya)
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
                    day_sales += round(row.total_price or 0)
                    day_count += 1
            weekly_chart.append({
                "label": day_label,
                "date": target_dt.strftime("%d-%m"),
                "sales": day_sales,
                "count": day_count
            })

        # 3. Oylik (So'nggi 4 hafta)
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
                    week_sales += round(row.total_price or 0)
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
            "sales_total": round(sales_total),
            "profit_total": round(profit_total),
            "ref_sales_count": ref_sales_count,
            "breakdown": [
                {
                    "name": "Stars (jami)",
                    "sales": round(stars_sales),
                    "cost": round(stars_cost),
                    "profit": round(stars_sales - stars_cost)
                },
                {
                    "name": "Premium (jami)",
                    "sales": round(prem_sales),
                    "cost": round(prem_cost),
                    "profit": round(prem_sales - prem_cost)
                },
                {
                    "name": "Sovg'alar (jami)",
                    "sales": round(gifts_sales),
                    "cost": round(gifts_cost),
                    "profit": round(gifts_sales - gifts_cost)
                }
            ],
            "top_products": [
                {"name": "100 ⭐ Stars", "count": 412},
                {"name": "Premium — 3 oy", "count": 96},
                {"name": "50 ⭐ Stars", "count": 88},
                {"name": "Teddy Bear sovg'a", "count": 21}
            ],
            "charts": {
                "daily": daily_chart,
                "weekly": weekly_chart,
                "monthly": monthly_chart
            }
        }

@app.get("/api/admin/pricing")
async def get_admin_pricing(admin: User = Depends(get_current_admin)):
    from app.services.fragment import pricing_engine
    async with AsyncSessionLocal() as session:
        pricing = await queries.get_pricing(session)
        frag_star_base = pricing_engine.get_star_base_cost()
        margin = pricing.margin_percent if pricing and pricing.margin_percent is not None else 20.0
        unit_sell = frag_star_base * (1 + margin / 100)

        discounts = []
        try:
            discounts = json.loads(pricing.stars_discounts_json) if pricing.stars_discounts_json else []
        except Exception:
            discounts = []

        prem_bases = pricing_engine.get_premium_base_costs()
        prem_prices = {}
        try:
            prem_prices = json.loads(pricing.premium_prices_json) if pricing.premium_prices_json else {}
        except Exception:
            prem_prices = {}
        
        # Ensure default prices if empty
        if not prem_prices:
            prem_prices = {"3": 143000, "6": 210000, "12": 380000}

        # Calculate margins
        prem_margins = {}
        for k in ["3", "6", "12"]:
            base = prem_bases.get(k, 140000)
            curr = prem_prices.get(k, base + 5000)
            prem_margins[k] = max(0, curr - base)

        gifts = []
        try:
            gifts = json.loads(pricing.gifts_json) if pricing.gifts_json else []
        except Exception:
            gifts = [
                {"id": "bear", "name": "Teddy Bear", "price_uzs": 64000, "icon": "🧸"},
                {"id": "heart", "name": "Neon Heart", "price_uzs": 85000, "icon": "💖"},
                {"id": "rocket", "name": "Cosmo Rocket", "price_uzs": 120000, "icon": "🚀"}
            ]

        gifts_bases = pricing_engine.get_gifts_base_costs()

        return {
            "stars_cost_ton": pricing.stars_cost_ton,
            "ton_rate_uzs": pricing.ton_rate_uzs,
            "margin_percent": margin,
            "fragment_stars_base_uzs": frag_star_base,
            "star_unit_price_uzs": frag_star_base,
            "unit_cost_uzs": frag_star_base,
            "unit_sell_uzs": round(unit_sell, 2),
            "discounts": discounts,
            "fragment_premium_bases": prem_bases,
            "premium_prices": prem_prices,
            "premium_margins": prem_margins,
            "gifts": gifts,
            "fragment_gifts_base_uzs": gifts_bases
        }

class PricingUpdateRequest(BaseModel):
    stars_cost_ton: float = 0.0021
    ton_rate_uzs: float = 14800.0
    margin_percent: float = 20.0
    star_unit_price_uzs: Optional[float] = None
    discounts: Optional[List[Dict[str, Any]]] = None
    premium_prices: Optional[Dict[str, Any]] = None
    premium_margins: Optional[Dict[str, Any]] = None
    gifts: Optional[List[Dict[str, Any]]] = None

@app.post("/api/admin/pricing")
async def update_admin_pricing(req: PricingUpdateRequest, admin: User = Depends(get_current_admin)):
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
            details=f"1 Stars: {req.star_unit_price_uzs} UZS, Marja: {req.margin_percent}%"
        )
        return {"success": True, "message": "Barcha narxlar muvaffaqiyatli saqlandi!"}

@app.get("/api/admin/orders")
async def get_admin_orders(
    search: Optional[str] = None,
    limit: int = 100,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        orders = await queries.list_all_orders(session, search=search, limit=limit)
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
                "total_price": round(o.total_price),
                "cost_price": round(o.cost_price),
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
    status: str # done, cancel, pending

@app.post("/api/admin/orders/{order_id}/status")
async def update_order_status_endpoint(
    order_id: int,
    req: OrderStatusUpdate,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        order = await queries.update_order_status(session, order_id, req.status)
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

        # Send notification to user about status change (done or cancel with refund)
        refund_amount = order.total_price if req.status == "cancel" else 0.0
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

        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Buyurtma holatini o'zgartirdi: {order.order_code}",
            details=f"Yangi holat: {req.status}"
        )
        return {"success": True, "status": order.status}

@app.post("/api/admin/orders/{order_id}/fulfill-fragment")
async def fulfill_order_fragment_endpoint(
    order_id: int,
    admin: User = Depends(get_current_admin)
):
    from app.services.fragment import fragment_client
    res = await fragment_client.fulfill_order(order_id=order_id, bot=bot_instance)
    return res

@app.get("/api/admin/fragment/settings")
async def get_fragment_settings_endpoint(admin: User = Depends(get_current_admin)):
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
            "min_ton_balance": s.min_ton_balance,
            "simulation_mode": s.simulation_mode,
            "wallet_balance_ton": balance
        }

class FragmentSettingsUpdate(BaseModel):
    is_auto_buy: Optional[bool] = None
    ton_wallet_address: Optional[str] = None
    ton_wallet_mnemonic: Optional[str] = None
    tonapi_key: Optional[str] = None
    network: Optional[str] = None
    min_ton_balance: Optional[float] = None
    simulation_mode: Optional[bool] = None

@app.post("/api/admin/fragment/settings")
async def update_fragment_settings_endpoint(
    req: FragmentSettingsUpdate,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        # If mnemonic is masked with dots, do not overwrite existing
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
    search: Optional[str] = None,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        users = await queries.list_users(session, search=search)
        from sqlalchemy import select, func
        result = []
        for u in users:
            # count user's orders and total purchase
            q = await session.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(Order.user_id == u.id, Order.status == "done")
            )
            count, total = q.first()
            result.append({
                "id": u.id,
                "first_name": u.first_name,
                "username": f"@{u.username}" if u.username else str(u.id),
                "role": u.role,
                "balance": round(u.balance),
                "orders_count": count or 0,
                "total_spent": round(total or 0.0),
                "referrals_count": u.referrals_count,
                "created_at": u.created_at.strftime("%d %b %Y") if u.created_at else ""
            })
        return result

@app.get("/api/admin/channels")
async def get_admin_channels(admin: User = Depends(get_current_admin)):
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
                "created_at": getattr(c, "created_at", None).strftime("%d %b, %H:%M") if getattr(c, "created_at", None) else ""
            }
            for c in channels
        ]

class ChannelCreateRequest(BaseModel):
    username_or_link: str
    title: Optional[str] = None
    req_type: str = "ordinary" # ordinary, join_request, external
    is_detected: bool = False

@app.post("/api/admin/channels")
async def create_channel_endpoint(
    req: ChannelCreateRequest,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        link = req.username_or_link.strip()
        title = (req.title or "").strip()

        # If title is empty, auto-detect title from Telegram
        if not title and bot_instance:
            try:
                target = link
                if "t.me/" in target:
                    target = target.split("t.me/")[-1].split("/")[0].replace("+", "")
                if not target.startswith("@") and not target.startswith("-100") and not target.isdigit():
                    target = f"@{target}"
                chat = await bot_instance.get_chat(target)
                title = chat.title or chat.full_name or link
            except Exception as err:
                logger.warning(f"Could not auto-fetch title for {link}: {err}")
                title = link
        elif not title:
            title = link

        # Smart detection of req_type if left as default ordinary
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
async def delete_channel_endpoint(
    channel_id: int,
    admin: User = Depends(get_current_admin)
):
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
async def toggle_channel_endpoint(
    channel_id: int,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        ch = await session.get(ChannelRequirement, channel_id)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        ch.is_active = not ch.is_active
        await session.commit()
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Kanal holatini o'zgartirdi (ID: {channel_id}, active: {ch.is_active})"
        )
        return {"success": True, "is_active": ch.is_active}

class ChannelConfirmRequest(BaseModel):
    req_type: str = "ordinary"

@app.post("/api/admin/channels/{channel_id}/confirm")
async def confirm_channel_endpoint(
    channel_id: int,
    req: ChannelConfirmRequest,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        ch = await queries.confirm_detected_channel(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Aniqlangan kanalni tasdiqladi va faollashtirdi: ID {channel_id}",
            details=f"{ch.title} ({ch.username_or_link}, {req.req_type})"
        )
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}
 
class ChannelTypeUpdateRequest(BaseModel):
    req_type: str

@app.post("/api/admin/channels/{channel_id}/type")
async def update_channel_type_endpoint(
    channel_id: int,
    req: ChannelTypeUpdateRequest,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        ch = await queries.update_channel_type(session, channel_id, req.req_type)
        if not ch:
            raise HTTPException(status_code=404, detail="Kanal topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Kanal shart turini o'zgartirdi: ID {channel_id}",
            details=f"{ch.title} ({ch.username_or_link}) -> {req.req_type}"
        )
        return {"success": True, "channel": {"id": ch.id, "title": ch.title, "req_type": ch.req_type}}

# ================= ADMIN PROMOCODES ================= #

@app.get("/api/admin/promocodes")
async def get_admin_promocodes(admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        promos = await queries.list_promo_codes(session)
        return [
            {
                "id": p.id,
                "code": p.code,
                "reward_type": p.reward_type,
                "reward_value": p.reward_value,
                "max_uses": p.max_uses,
                "current_uses": p.current_uses,
                "min_order_amount": p.min_order_amount,
                "is_active": p.is_active,
                "created_at": p.created_at.strftime("%d %b %Y") if p.created_at else ""
            }
            for p in promos
        ]

class PromoCreateRequest(BaseModel):
    code: str
    reward_type: str = "discount_percent" # discount_percent, balance_bonus
    reward_value: float = 10.0
    max_uses: int = 100
    min_order_amount: float = 0.0
    is_active: bool = True

@app.post("/api/admin/promocodes")
async def create_admin_promocode(req: PromoCreateRequest, admin: User = Depends(get_current_admin)):
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
                details=f"{promo.code} ({promo.reward_type}: {promo.reward_value})"
            )
            return {"success": True, "promo_id": promo.id}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/admin/promocodes/{promo_id}")
async def delete_admin_promocode(promo_id: int, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        deleted = await queries.delete_promo_code(session, promo_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Promo-kodni o'chirdi",
            details=f"Promo ID: {promo_id}"
        )
        return {"success": True}

@app.post("/api/admin/promocodes/{promo_id}/toggle")
async def toggle_admin_promocode(promo_id: int, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        promo = await queries.toggle_promo_code(session, promo_id)
        if not promo:
            raise HTTPException(status_code=404, detail="Promo-kod topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Promo-kod holatini o'zgartirdi",
            details=f"{promo.code} faol: {promo.is_active}"
        )
        return {"success": True, "is_active": promo.is_active}

@app.get("/api/admin/payments")
async def get_payment_settings_endpoint(admin: User = Depends(get_current_admin)):
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
            "autopaycard_email": p.autopaycard_email if p else "payments.stellar@gmail.com",
            "autopaycard_webhook_url": p.autopaycard_webhook_url if p else "https://stellar-bot.uz/webhook/autopaycard"
        }

class PaymentSettingsUpdate(BaseModel):
    click_active: bool = True
    payme_active: bool = True
    card_active: bool = True
    card_number: Optional[str] = "8600 1234 5678 9012"
    card_holder: Optional[str] = "ANVAR S."
    bank_name: Optional[str] = "TBC Bank"
    autopaycard_active: bool = False
    autopaycard_api_key: Optional[str] = None
    autopaycard_last4: Optional[str] = None
    autopaycard_email: Optional[str] = None

@app.post("/api/admin/payments")
async def update_payment_settings_endpoint(
    req: PaymentSettingsUpdate,
    admin: User = Depends(get_current_admin)
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

        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="To'lov tizimlari va karta sozlamalarini yangiladi",
            details=f"Click: {p.click_active}, Payme: {p.payme_active}, Karta: {p.card_active} ({p.card_number})"
        )
        return {"success": True}

# ================= PAYMENT CARDS API ================= #

class PaymentCardCreate(BaseModel):
    card_number: str
    card_holder: str
    bank_name: str
    card_type: str = "UZCARD"
    is_active: bool = True

class PaymentCardUpdate(BaseModel):
    card_number: Optional[str] = None
    card_holder: Optional[str] = None
    bank_name: Optional[str] = None
    card_type: Optional[str] = None
    is_active: Optional[bool] = None

@app.get("/api/admin/cards")
async def get_admin_cards_endpoint(admin: User = Depends(get_current_admin)):
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
async def create_admin_card_endpoint(req: PaymentCardCreate, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        c = await queries.create_payment_card(
            session=session,
            card_number=req.card_number,
            card_holder=req.card_holder,
            bank_name=req.bank_name,
            card_type=req.card_type,
            is_active=req.is_active
        )
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Yangi bank kartasi qo'shdi",
            details=f"Karta: {c.bank_name} ({c.card_number}) - {c.card_holder}"
        )
        return {"success": True, "id": c.id}

@app.put("/api/admin/cards/{card_id}")
async def update_admin_card_endpoint(card_id: int, req: PaymentCardUpdate, admin: User = Depends(get_current_admin)):
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
async def delete_admin_card_endpoint(card_id: int, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_payment_card(session, card_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Karta topilmadi")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Bank kartasini o'chirdi",
            details=f"ID: {card_id}"
        )
        return {"success": True}


@app.get("/api/admin/referral")
async def get_referral_settings_endpoint(admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        return {
            "bonus_percent": r.bonus_percent if r else 5.0,
            "min_purchase_uzs": r.min_purchase_uzs if r else 20000.0,
            "auto_reward": r.auto_reward if r else True,
            "require_purchase": r.require_purchase if r else True
        }

class ReferralSettingsUpdate(BaseModel):
    bonus_percent: float
    min_purchase_uzs: float
    auto_reward: bool
    require_purchase: bool

@app.post("/api/admin/referral")
async def update_referral_settings_endpoint(
    req: ReferralSettingsUpdate,
    admin: User = Depends(get_current_admin)
):
    async with AsyncSessionLocal() as session:
        r = await session.get(ReferralSetting, 1)
        if not r:
            r = ReferralSetting(id=1)
            session.add(r)
        r.bonus_percent = req.bonus_percent
        r.min_purchase_uzs = req.min_purchase_uzs
        r.auto_reward = req.auto_reward
        r.require_purchase = req.require_purchase
        await session.commit()

        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action="Referal sozlamalarini yangiladi",
            details=f"Bonus: {req.bonus_percent}%, Min xarid: {req.min_purchase_uzs} so'm"
        )
        return {"success": True}

@app.get("/api/admin/admins")
async def get_admins_list(admin: User = Depends(get_current_admin)):
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
    identifier: str # either user_id or @username
    role: str # super_admin, price_admin, support_admin, marketing_admin

@app.post("/api/admin/admins")
async def add_admin_endpoint(req: AddAdminRequest, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        target_user = None
        ident = req.identifier.strip()

        if ident.isdigit():
            target_user = await queries.get_user_by_id(session, int(ident))
        else:
            target_user = await queries.get_user_by_username(session, ident)

        if not target_user:
            raise HTTPException(
                status_code=404,
                detail=f"Foydalanuvchi topilmadi! U avval botga yozgan/ro'yxatdan o'tgan bo'lishi kerak: {ident}"
            )

        updated = await queries.set_user_role(session, target_user.id, req.role)
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Yangi admin tayinladi: @{updated.username or updated.id}",
            details=f"Rol: {req.role}"
        )
        return {"success": True, "message": f"@{updated.username or updated.id} ga '{req.role}' roli berildi!"}

@app.delete("/api/admin/admins/{user_id}")
async def revoke_admin_endpoint(user_id: int, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        if str(user_id) in config.ADMINS and admin.id != user_id:
            raise HTTPException(status_code=400, detail="Bosh adminni olib tashlab bo'lmaydi!")
        await queries.set_user_role(session, user_id, "user")
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Admin huquqini bekor qildi: ID {user_id}"
        )
        return {"success": True}

@app.get("/api/admin/audit-logs")
async def get_audit_logs(admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        logs = await queries.list_audit_logs(session, limit=50)
        return [
            {
                "id": l.id,
                "admin": f"@{l.admin_username}" if l.admin_username else f"ID {l.admin_id}",
                "action": l.action,
                "details": l.details,
                "created_at": l.created_at.strftime("%d %b, %H:%M") if l.created_at else ""
            }
            for l in logs
        ]

class BroadcastRequest(BaseModel):
    segment: str = "all" # all, non_buyers, active, referral
    mode: str = "write" # write, post_link, forward, postbot
    text: Optional[str] = None
    photo_url: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    buttons: Optional[List[Dict[str, str]]] = None # [{"text": "...", "url": "..."}]
    post_link: Optional[str] = None # e.g. https://t.me/channel/123
    forward_mode: bool = False # True = forward_message, False = copy_message
    postbot_code: Optional[str] = None
    draft_id: Optional[int] = None

latest_broadcast_status = {
    "is_running": False,
    "total": 0,
    "sent": 0,
    "blocked": 0,
    "failed": 0,
    "completed_at": None
}

@app.get("/api/admin/broadcast/status")
async def get_broadcast_status(admin: User = Depends(get_current_admin)):
    return latest_broadcast_status

@app.get("/api/admin/broadcast/latest-draft")
async def get_latest_broadcast_draft_endpoint(admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(BroadcastDraft).order_by(BroadcastDraft.id.desc()).limit(1)
        )
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
async def send_broadcast_endpoint(req: BroadcastRequest, admin: User = Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        recipients = await queries.get_broadcast_recipients(session, req.segment)

        # Log action
        await queries.log_admin_action(
            session=session,
            admin_id=admin.id,
            admin_username=admin.username,
            action=f"Broadcast boshlandi: {len(recipients)} ta foydalanuvchiga",
            details=f"Segment: {req.segment}, Rejim: {req.mode}"
        )

        # Non-blocking async queue delivery with rate limit ~30/sec
        asyncio.create_task(run_broadcast_queue(recipients, req, admin_id=admin.id))

        return {
            "success": True,
            "recipients_count": len(recipients),
            "message": f"Broadcast {len(recipients)} ta foydalanuvchiga yuborilmoqda... Tugagach Telegramingizga hisobot yuboriladi!"
        }

async def run_broadcast_queue(recipients: List[int], req: BroadcastRequest, admin_id: Optional[int] = None):
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

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

    # Construct multiple inline buttons if provided
    inline_keyboard = []
    if req.buttons:
        for b in req.buttons:
            t = (b.get("text") or "").strip()
            u = (b.get("url") or "").strip()
            if t and u and (u.startswith("https://") or u.startswith("http://") or u.startswith("tg://")):
                inline_keyboard.append([InlineKeyboardButton(text=t, url=u)])
    elif req.button_text:
        b_url = req.button_url or config.WEB_APP_URL
        if b_url.startswith("https://") or b_url.startswith("http://"):
            inline_keyboard.append([InlineKeyboardButton(text=req.button_text, url=b_url)])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard) if inline_keyboard else None

    # Parse channel post link if provided
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
            logger.warning(f"Failed to parse broadcast post link ({req.post_link}): {e}")

    if not post_info and req.draft_id:
        async with AsyncSessionLocal() as session:
            draft = await session.get(BroadcastDraft, req.draft_id)
            if draft and draft.forward_chat_id and draft.forward_message_id:
                post_info = (draft.forward_chat_id, draft.forward_message_id)

    for uid in recipients:
        try:
            if post_info:
                chat_ref, msg_id = post_info
                if req.forward_mode:
                    await bot_instance.forward_message(
                        chat_id=uid,
                        from_chat_id=chat_ref,
                        message_id=msg_id
                    )
                else:
                    await bot_instance.copy_message(
                        chat_id=uid,
                        from_chat_id=chat_ref,
                        message_id=msg_id,
                        reply_markup=reply_markup
                    )
            elif req.photo_url and req.photo_url.startswith("http"):
                await bot_instance.send_photo(
                    chat_id=uid,
                    photo=req.photo_url,
                    caption=req.text or "",
                    reply_markup=reply_markup
                )
            elif req.text:
                await bot_instance.send_message(
                    chat_id=uid,
                    text=req.text,
                    reply_markup=reply_markup
                )
            latest_broadcast_status["sent"] += 1
            await asyncio.sleep(0.04) # ~25-30 messages per second rate limiter
        except TelegramForbiddenError:
            latest_broadcast_status["blocked"] += 1
        except Exception as e:
            latest_broadcast_status["failed"] += 1

    latest_broadcast_status["is_running"] = False
    latest_broadcast_status["completed_at"] = datetime.utcnow().strftime("%d %b %Y, %H:%M")

    # Send receipt directly to the admin in Telegram
    if admin_id and bot_instance:
        report_text = (
            f"📢 <b>Broadcast xabarnomasi yakunlandi!</b>\n\n"
            f"👥 <b>Jami rejalashtirilgan:</b> {latest_broadcast_status['total']} ta\n"
            f"✅ <b>Muvaffaqiyatli yetkazildi:</b> {latest_broadcast_status['sent']} ta\n"
            f"🚫 <b>Botni bloklagan:</b> {latest_broadcast_status['blocked']} ta\n"
            f"⚠️ <b>Xatoliklar:</b> {latest_broadcast_status['failed']} ta\n"
            f"⏱ <b>Vaqt:</b> {latest_broadcast_status['completed_at']}"
        )
        try:
            await bot_instance.send_message(chat_id=admin_id, text=report_text)
        except Exception:
            pass

@app.get("/api/admin/export/orders.csv")
async def export_orders_csv(admin: User = Depends(get_current_admin)):
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
                round(o.total_price),
                round(o.cost_price),
                o.status,
                o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""
            ])

        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=stellar_orders.csv"}
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
    name: Optional[str] = None
    price_uzs: Optional[float] = None
    cost_uzs: Optional[float] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

@app.get("/api/admin/services")
async def api_admin_list_services():
    async with AsyncSessionLocal() as session:
        services = await queries.list_custom_services(session=session, active_only=False)
        return [
            {
                "id": s.id,
                "name": s.name,
                "price_uzs": s.price_uzs,
                "cost_uzs": s.cost_uzs,
                "category": s.category,
                "icon": s.icon,
                "description": s.description,
                "is_active": s.is_active,
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""
            }
            for s in services
        ]

@app.post("/api/admin/services")
async def api_admin_create_service(req: CreateServiceRequest):
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
async def api_admin_update_service(service_id: int, req: UpdateServiceRequest):
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
async def api_admin_delete_service(service_id: int):
    async with AsyncSessionLocal() as session:
        ok = await queries.delete_custom_service(session=session, service_id=service_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Xizmat topilmadi")
        return {"success": True, "message": "Xizmat o'chirildi"}

# ================= HTML FRONTEND SERVING ================= #

@app.get("/app", response_class=HTMLResponse)
async def serve_user_app():
    user_app_path = os.path.join(config.BASE_DIR, "web", "user", "index.html")
    if os.path.exists(user_app_path):
        with open(user_app_path, "r", encoding="utf-8") as f:
            return f.read()
    # Fallback to mockup if not yet generated
    mockup_path = os.path.join(config.BASE_DIR, "stellar-bot-mockup.html")
    with open(mockup_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_app():
    admin_app_path = os.path.join(config.BASE_DIR, "web", "admin", "index.html")
    if os.path.exists(admin_app_path):
        with open(admin_app_path, "r", encoding="utf-8") as f:
            return f.read()
    mockup_path = os.path.join(config.BASE_DIR, "stellar-bot-admin-mockup.html")
    with open(mockup_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/")
async def root_redirect():
    return HTMLResponse("""
    <html>
      <head><title>Stellar Bot</title></head>
      <body style="background:#080C0A;color:#EFFBF4;font-family:sans-serif;text-align:center;padding:50px;">
        <h2>⭐ Stellar Bot Xizmati</h2>
        <p>Telegram Stars, Premium va Sovg'alar platformasi</p>
        <div style="margin-top:20px;">
          <a href="/app" style="color:#12E88B;margin-right:20px;font-size:16px;">Web App (User)</a>
          <a href="/admin" style="color:#BFFFDD;font-size:16px;">Admin Panel</a>
        </div>
      </body>
    </html>
    """)
