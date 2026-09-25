import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import GiftHubException, InsufficientBalanceError, PriceExpiredError
from app.models.user import User
from app.services.orders.service import order_service
from app.utils.notifications import send_admin_order_alert, send_order_created_notification
from app.web.auth import get_current_user
from app.web.state import get_bot
from database import queries

router = APIRouter(tags=["Orders"])


class PurchaseRequest(BaseModel):
    product_type: str  # stars, premium, gift, service
    item_title: str
    amount: int = 1
    recipient_username: str | None = None
    promo_code: str | None = None
    price_lock_id: str | None = None


@router.post("/api/orders/create")
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

        # Queue resilient notification via Outbox (Req 7)
        u = await queries.get_user_by_id(session, user.id)
        current_bal = float(u.balance) if u else 0.0

        if bot:
            try:
                from app.services.outbox.service import outbox_service
                await outbox_service.create_event(
                    session=session,
                    event_type="ORDER_CREATED_NOTIFICATION",
                    aggregate_type="order",
                    aggregate_id=str(order.id),
                    payload={
                        "order": {
                            "id": order.id,
                            "order_code": order.order_code,
                            "item_title": order.item_title,
                            "amount": order.amount,
                            "total_price": float(order.total_price),
                            "cost_price": float(order.cost_price),
                            "status": order.status,
                            "recipient_username": req.recipient_username,
                            "buyer_username": user.username,
                            "user_id": user.id,
                            "user_first_name": user.first_name,
                            "new_balance": current_bal
                        }
                    }
                )
                await session.commit()
            except Exception as e:
                logger.warning(f"Failed to queue order notification outbox event: {e}")

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


@router.get("/api/orders/history")
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


@router.get("/receipt/{order_code}", response_class=HTMLResponse)
async def view_order_receipt_html(order_code: str):
    """Generates a clean, printable digital receipt for an order."""
    async with AsyncSessionLocal() as session:
        from app.services.orders.service import order_service
        receipt = await order_service.get_order_receipt(session, order_code)
        if not receipt:
            return HTMLResponse("<h3>Chek topilmadi</h3>", status_code=404)

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>GiftHub Chek #{receipt['order_code']}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; display: flex; justify-content: center; }}
  .receipt-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 16px; width: 100%; max-width: 440px; padding: 24px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
  .brand {{ text-align: center; font-size: 24px; font-weight: 800; color: #38bdf8; margin-bottom: 8px; }}
  .subtitle {{ text-align: center; font-size: 13px; color: #94a3b8; margin-bottom: 24px; }}
  .line {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #334155; font-size: 14px; }}
  .line.total {{ font-size: 18px; font-weight: 700; color: #4ade80; border-top: 2px dashed #475569; margin-top: 12px; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 999px; background: rgba(56,189,248,0.15); color: #38bdf8; font-weight: 600; font-size: 12px; }}
  .footer {{ text-align: center; margin-top: 24px; font-size: 12px; color: #64748b; }}
</style>
</head>
<body>
<div class="receipt-box">
  <div class="brand">🎁 GiftHub</div>
  <div class="subtitle">Raqamli Xarid Kvitansiyasi</div>
  <div class="line"><span>Buyurtma kodi:</span><span class="badge">#{receipt['order_code']}</span></div>
  <div class="line"><span>Sana:</span><span>{receipt['created_at'][:19] if receipt.get('created_at') else 'N/A'}</span></div>
  <div class="line"><span>Mahsulot:</span><b>{receipt['item_title']}</b></div>
  <div class="line"><span>Miqdor:</span><span>{receipt['amount']}</span></div>
  <div class="line"><span>Qabul qiluvchi:</span><span>{receipt['recipient']}</span></div>
  <div class="line"><span>To'lov usuli:</span><span style="text-transform: uppercase;">{receipt['payment_method']}</span></div>
  <div class="line total"><span>Jami to'landi:</span><span>{receipt['formatted_total']}</span></div>
  <div class="footer">Xaridingiz uchun rahmat! • GiftHub Telegram Platformasi</div>
</div>
</body>
</html>"""
        return HTMLResponse(html)
