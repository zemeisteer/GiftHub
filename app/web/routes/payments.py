from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.payment import PaymentSetting
from app.models.user import User
from app.services.payments import (
    generate_click_link,
    generate_payme_link,
    handle_autopaycard_webhook,
    handle_payme_request,
    process_click_complete,
    process_click_prepare,
    verify_payme_auth,
)
from app.services.wallet.service import wallet_service
from app.web.auth import get_current_user
from app.web.state import get_bot

router = APIRouter(tags=["Payments & Topup"])


class TopupRequest(BaseModel):
    amount: float
    method: str  # click, payme, autopaycard, test_demo


@router.post("/api/wallet/topup")
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
                note=f"Test demo hisob to'ldirildi ({req.method})",
            )
            await session.commit()
            return {
                "success": True,
                "dev_mode": True,
                "new_balance": round(float(updated_user.balance)),
                "amount": float(dec_amount),
                "method": req.method,
                "message": f"[DEV] Hamyon to'ldirildi: +{dec_amount:,.0f} so'm",
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
                "amount": float(dec_amount),
            }
    else:
        raise HTTPException(status_code=400, detail="Noma'lum to'lov usuli")


class CheckoutLinkRequest(BaseModel):
    amount: float
    method: str


@router.post("/api/wallet/checkout-link")
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
                "amount": float(dec_amount),
            }
    else:
        raise HTTPException(status_code=400, detail="Noma'lum to'lov usuli")


# ================= OFFICIAL PAYMENT WEBHOOKS ================= #


@router.post("/api/payments/click")
@router.post("/api/payments/click/prepare")
@router.post("/api/payments/click/complete")
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
        bot = get_bot()
        if action == 0:
            result = await process_click_prepare(session, data)
        elif action == 1:
            result = await process_click_complete(session, data, bot=bot)
        else:
            result = {"error": -3, "error_note": "Action not found"}
        return JSONResponse(result)


@router.post("/api/payments/payme")
async def payme_webhook_handler(request: Request):
    auth_header = request.headers.get("authorization")
    if not verify_payme_auth(auth_header):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32504, "message": "Avtorizatsiya xatosi"}}
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON xatosi"}})

    async with AsyncSessionLocal() as session:
        bot = get_bot()
        result = await handle_payme_request(session, payload, bot=bot)
        return JSONResponse(result)


@router.post("/api/payments/autopaycard")
async def autopaycard_webhook_handler(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = dict(await request.form())

    headers = dict(request.headers)
    async with AsyncSessionLocal() as session:
        bot = get_bot()
        result = await handle_autopaycard_webhook(session, payload, headers=headers, bot=bot)
        return JSONResponse(result)
