from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.core.correlation import get_correlation_id
from app.core.database import AsyncSessionLocal
from app.core.exceptions import GiftHubException, InsufficientBalanceError
from app.core.logging import get_logger
from app.core.security import Permission
from app.models.audit import AdminAuditLog
from app.models.catalog import CatalogProduct
from app.models.dlq import DLQStatus, FailedJob
from app.models.feature_flags import FeatureFlag
from app.models.fragment import FragmentSetting
from app.models.order import Order, OrderStatus, OrderStatusHistory
from app.models.outbox import OutboxEvent
from app.models.payment import PaymentSetting, PaymentTransaction
from app.models.pricing import PricingSetting
from app.models.provider import ProviderHealth, ProviderStatus
from app.models.recipient import SavedRecipient
from app.models.reconciliation import ReconciliationDiscrepancy, ReconciliationReport
from app.services.catalog.service import catalog_service
from app.services.dlq.service import dlq_service
from app.services.feature_flags.service import feature_flag_service
from app.services.fulfillment.service import fulfillment_service
from app.services.orders.service import order_service
from app.services.pricing.service import pricing_service
from app.services.providers.circuit_breaker import circuit_breaker
from app.services.reconciliation.service import reconciliation_service
from app.services.wallet.service import wallet_service

logger = get_logger("GiftHubV1API")

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ================= SCHEMAS ================= #


class CheckoutRequest(BaseModel):
    user_id: int
    product_type: str  # stars, premium, gift, service
    quantity: int = 1
    recipient_username: Optional[str] = None
    promo_code: Optional[str] = None
    price_lock_id: Optional[str] = None
    payment_method: str = "balance"


class PricePreviewRequest(BaseModel):
    ton_rate_uzs: Optional[Decimal] = None
    margin_percent: Optional[Decimal] = None
    stars_cost_ton: Optional[Decimal] = None
    star_unit_price_uzs: Optional[Decimal] = None


class SavedRecipientCreate(BaseModel):
    user_id: int
    recipient_username: str
    label: Optional[str] = None


class ReasonedAdminAction(BaseModel):
    reason: str = Field(..., min_length=5, description="Auditing reason is mandatory for sensitive actions")
    notes: Optional[str] = None


class ProviderStatusUpdate(ReasonedAdminAction):
    status: str  # healthy, degraded, disabled


class FeatureFlagUpdate(BaseModel):
    is_enabled: bool
    description: Optional[str] = None


class CatalogProductCreate(BaseModel):
    category: str
    sku: str
    title: str
    base_price_uzs: Decimal
    quantity: int = 1
    duration_months: Optional[int] = None
    description: Optional[str] = None
    badge_text: Optional[str] = None
    display_order: int = 0


# ================= CATALOG (Req 16) ================= #


@router.get("/catalog")
async def get_public_catalog(category: Optional[str] = None, session=Depends(get_db)):
    """Returns database-driven product catalog for Stars bundles, Premium, and Gifts."""
    products = await catalog_service.list_products(session, category=category, active_only=True)
    return {
        "success": True,
        "products": [
            {
                "id": p.id,
                "category": p.category,
                "sku": p.sku,
                "title": p.title,
                "quantity": p.quantity,
                "duration_months": p.duration_months,
                "base_price_uzs": float(p.base_price_uzs),
                "badge_text": p.badge_text,
                "description": p.description,
                "display_order": p.display_order,
            }
            for p in products
        ],
    }


# ================= CHECKOUT WITH IDEMPOTENCY (Req 7 & Req 8) ================= #


@router.post("/orders/checkout")
async def create_checkout_order(
    req: CheckoutRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session=Depends(get_db),
):
    """
    Creates an order with authoritative pricing, checkout-level idempotency,
    and automatic Outbox event scheduling.
    """
    cid = correlation_id or get_correlation_id()
    try:
        order, bonus, referrer = await order_service.create_order(
            session=session,
            user_id=req.user_id,
            product_type=req.product_type,
            item_title=f"{req.quantity} {req.product_type.title()}",
            amount=req.quantity,
            recipient_username=req.recipient_username,
            promo_code_str=req.promo_code,
            price_lock_id=req.price_lock_id,
            payment_method=req.payment_method,
            idempotency_key=idempotency_key,
            correlation_id=cid,
        )
        return {
            "success": True,
            "order": {
                "id": order.id,
                "order_code": order.order_code,
                "status": order.status,
                "total_price": float(order.total_price),
                "payment_method": order.payment_method,
                "fulfillment_status": order.fulfillment_status,
                "correlation_id": cid,
            },
        }
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GiftHubException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Checkout error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Buyurtmani yaratishda server xatoligi yuz berdi.")


# ================= RECONCILIATION & DASHBOARD (Req 2 & Req 17) ================= #


@router.get("/admin/reconciliation/dashboard")
async def get_reconciliation_dashboard(session=Depends(get_db)):
    """Financial reconciliation overview: payments received, ledger, orders, and discrepancies."""
    stats = await reconciliation_service.get_dashboard_stats(session)
    return {"success": True, "data": stats}


@router.post("/admin/reconciliation/audit")
async def trigger_reconciliation_audit(session=Depends(get_db)):
    """Triggers an on-demand reconciliation scan across payments, orders, and ledger."""
    report = await reconciliation_service.run_reconciliation_audit(session)
    return {
        "success": True,
        "report_id": report.id,
        "status": report.status,
        "payments_checked": report.total_payments_checked,
        "orders_checked": report.total_orders_checked,
        "discrepancies_found": report.discrepancies_count,
    }


@router.get("/admin/reconciliation/discrepancies")
async def list_discrepancies(is_resolved: Optional[bool] = Query(None), limit: int = 50, session=Depends(get_db)):
    from sqlalchemy import select

    stmt = select(ReconciliationDiscrepancy).order_by(ReconciliationDiscrepancy.created_at.desc())
    if is_resolved is not None:
        stmt = stmt.where(ReconciliationDiscrepancy.is_resolved == is_resolved)
    res = await session.execute(stmt.limit(limit))
    items = res.scalars().all()
    return {
        "success": True,
        "discrepancies": [
            {
                "id": d.id,
                "report_id": d.report_id,
                "type": d.discrepancy_type,
                "order_id": d.order_id,
                "payment_id": d.payment_id,
                "expected": d.expected_value,
                "actual": d.actual_value,
                "details": d.details,
                "is_resolved": d.is_resolved,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in items
        ],
    }


@router.post("/admin/reconciliation/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(discrepancy_id: int, action: ReasonedAdminAction, session=Depends(get_db)):
    disc = await session.get(ReconciliationDiscrepancy, discrepancy_id)
    if not disc:
        raise HTTPException(status_code=404, detail="Discrepancy record topilmadi.")
    disc.is_resolved = True
    disc.resolution_notes = action.reason
    disc.resolved_at = datetime.now(timezone.utc)
    await session.flush()
    return {"success": True, "message": "Discrepancy belgilandi va hal qilindi."}


# ================= DEAD LETTER QUEUE (DLQ) (Req 4) ================= #


@router.get("/admin/dlq")
async def list_dlq_jobs(
    job_status: Optional[str] = Query(None, alias="status"), limit: int = 50, session=Depends(get_db)
):
    jobs = await dlq_service.list_failed_jobs(session, status=job_status, limit=limit)
    return {
        "success": True,
        "jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "order_id": j.order_id,
                "payload": j.payload,
                "error_message": j.error_message,
                "attempts": j.attempts,
                "status": j.status,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
    }


@router.post("/admin/dlq/{job_id}/retry")
async def retry_dlq_job(job_id: int, session=Depends(get_db)):
    job = await dlq_service.mark_retrying(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="DLQ job topilmadi.")
    return {"success": True, "message": f"Job #{job_id} qayta urinish navbatiga qo'yildi."}


@router.post("/admin/dlq/{job_id}/resolve")
async def resolve_dlq_job(job_id: int, action: ReasonedAdminAction, session=Depends(get_db)):
    job = await dlq_service.resolve_job(session, job_id, admin_id=0, notes=action.reason)
    if not job:
        raise HTTPException(status_code=404, detail="DLQ job topilmadi.")
    return {"success": True, "message": f"Job #{job_id} muvaffaqiyatli hal qilindi."}


# ================= PROVIDER HEALTH & CIRCUIT BREAKER (Req 5 & Req 19) ================= #


@router.get("/admin/providers")
async def list_providers(session=Depends(get_db)):
    from sqlalchemy import select

    res = await session.execute(select(ProviderHealth))
    providers = res.scalars().all()
    result = []
    for p in providers:
        st = circuit_breaker._get_or_init_state(p.provider_name)
        result.append(
            {
                "provider_name": p.provider_name,
                "status": p.status,
                "circuit_state": st["state"],
                "failure_count": p.failure_count,
                "success_count": p.success_count,
                "consecutive_failures": st["consecutive_failures"],
                "disabled_reason": p.disabled_reason,
            }
        )
    return {"success": True, "providers": result}


@router.post("/admin/providers/{provider_name}/status")
async def update_provider_status(provider_name: str, action: ProviderStatusUpdate, session=Depends(get_db)):
    """Enforces reason & confirmation for provider disabling."""
    ph = await session.get(ProviderHealth, provider_name)
    now = datetime.now(timezone.utc)
    if not ph:
        ph = ProviderHealth(provider_name=provider_name, updated_at=now)
        session.add(ph)

    ph.status = action.status.lower()
    ph.disabled_reason = action.reason
    ph.updated_at = now

    audit = AdminAuditLog(
        admin_id=0,
        action="update_provider_status",
        entity_type="provider",
        entity_id=provider_name,
        reason=action.reason,
        details=f"Provider {provider_name} holati '{action.status}' ga o'zgartirildi. Sabab: {action.reason}",
        created_at=now,
    )
    session.add(audit)
    await session.flush()
    return {"success": True, "message": f"Provider {provider_name} holati yangilandi."}


# ================= FEATURE FLAGS (Req 6) ================= #


@router.get("/admin/feature-flags")
async def get_feature_flags(session=Depends(get_db)):
    flags = await feature_flag_service.list_all_flags(session)
    return {
        "success": True,
        "flags": [{"name": f.name, "is_enabled": f.is_enabled, "description": f.description} for f in flags],
    }


@router.post("/admin/feature-flags/{name}")
async def set_feature_flag(name: str, req: FeatureFlagUpdate, session=Depends(get_db)):
    flag = await feature_flag_service.set_flag(session, name, req.is_enabled, req.description)
    return {"success": True, "flag": {"name": flag.name, "is_enabled": flag.is_enabled}}


# ================= CATALOG ADMIN (Req 16) ================= #


@router.get("/admin/catalog")
async def get_admin_catalog(session=Depends(get_db)):
    products = await catalog_service.list_products(session, active_only=False)
    return {
        "success": True,
        "products": [
            {
                "id": p.id,
                "category": p.category,
                "sku": p.sku,
                "title": p.title,
                "quantity": p.quantity,
                "duration_months": p.duration_months,
                "base_price_uzs": float(p.base_price_uzs),
                "is_active": p.is_active,
                "badge_text": p.badge_text,
                "display_order": p.display_order,
            }
            for p in products
        ],
    }


@router.post("/admin/catalog")
async def create_catalog_item(item: CatalogProductCreate, session=Depends(get_db)):
    prod = await catalog_service.create_product(
        session=session,
        category=item.category,
        sku=item.sku,
        title=item.title,
        base_price_uzs=item.base_price_uzs,
        quantity=item.quantity,
        duration_months=item.duration_months,
        description=item.description,
        badge_text=item.badge_text,
        display_order=item.display_order,
    )
    return {"success": True, "product_id": prod.id}


# ================= SYSTEM HEALTH (Req 8) ================= #


@router.get("/admin/health/system")
@router.get("/health/system")
async def get_system_health(session=Depends(get_db)):
    """
    Consolidated System Health dashboard payload (Req 8):
    Bot, PostgreSQL, Redis, Workers, Payment Providers, Fulfillment, Queue Depth, Failed Jobs.
    """
    import time

    from sqlalchemy import text

    from app.core.config import settings
    from app.core.database import engine
    from app.core.redis import get_redis_client
    from app.services.worker import get_worker_status

    # 1. Bot status
    from app.web.server import bot_instance, bot_username

    bot_info = {
        "status": "online" if (bot_instance and settings.BOT_TOKEN) else "degraded",
        "username": bot_username or "gifthub_bot",
        "mode": getattr(settings, "TELEGRAM_MODE", "polling"),
        "has_token": bool(settings.BOT_TOKEN),
    }

    # 2. Database status
    t0 = time.perf_counter()
    db_ok = False
    db_latency = None
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
        db_latency = round((time.perf_counter() - t0) * 1000, 2)
    except Exception as e:
        logger.error(f"System health DB check failed: {e}")

    db_info = {
        "status": "connected" if db_ok else "disconnected",
        "latency_ms": db_latency,
        "engine": engine.dialect.name,
    }

    # 3. Redis status
    r_client = get_redis_client()
    redis_ok = False
    redis_latency = None
    if r_client:
        t0 = time.perf_counter()
        try:
            pong = await r_client.ping()
            redis_ok = bool(pong)
            redis_latency = round((time.perf_counter() - t0) * 1000, 2)
        except Exception:
            redis_ok = False
    else:
        redis_ok = settings.ENVIRONMENT != "production"

    redis_info = {
        "status": "connected" if redis_ok else "disconnected",
        "latency_ms": redis_latency,
        "fsm_storage": "RedisStorage" if (r_client and settings.REDIS_URL) else "MemoryStorage",
    }

    # 4. Worker status
    worker_info = get_worker_status()

    # 5. Payment providers
    pay_setting = await session.get(PaymentSetting, 1)
    payment_providers = {
        "click": {
            "is_active": pay_setting.click_active if pay_setting else True,
            "circuit": circuit_breaker.get_state("click").value,
            "status": "healthy" if circuit_breaker.get_state("click").value == "CLOSED" else "degraded",
        },
        "payme": {
            "is_active": pay_setting.payme_active if pay_setting else True,
            "circuit": circuit_breaker.get_state("payme").value,
            "status": "healthy" if circuit_breaker.get_state("payme").value == "CLOSED" else "degraded",
        },
        "autopaycard": {
            "is_active": pay_setting.autopaycard_active if pay_setting else False,
            "circuit": circuit_breaker.get_state("autopaycard").value,
            "status": "healthy" if circuit_breaker.get_state("autopaycard").value == "CLOSED" else "degraded",
        },
    }

    # 6. Fulfillment providers
    frag_setting = await session.get(FragmentSetting, 1)
    frag_circuit = circuit_breaker.get_state("fragment").value
    fulfillment_providers = {
        "fragment": {
            "auto_buy": frag_setting.is_auto_buy if frag_setting else True,
            "simulation_mode": frag_setting.simulation_mode if frag_setting else False,
            "circuit": frag_circuit,
            "status": "operational" if frag_circuit != "OPEN" else "degraded",
        }
    }

    # 7. Queue depth
    res_outbox = await session.execute(select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "pending"))
    pending_outbox = res_outbox.scalar() or 0

    res_unproc_orders = await session.execute(
        select(func.count(Order.id)).where(Order.status == "paid", Order.fulfillment_status == "pending")
    )
    unproc_orders = res_unproc_orders.scalar() or 0

    queue_depth = {
        "pending_outbox_events": pending_outbox,
        "unfulfilled_paid_orders": unproc_orders,
        "in_memory_queue_size": worker_info["queue_size"],
    }

    # 8. Failed jobs (DLQ)
    res_exhausted = await session.execute(select(func.count(FailedJob.id)).where(FailedJob.status == "exhausted"))
    exhausted_dlq = res_exhausted.scalar() or 0

    res_retrying = await session.execute(select(func.count(FailedJob.id)).where(FailedJob.status == "retrying"))
    retrying_dlq = res_retrying.scalar() or 0

    failed_jobs = {
        "exhausted_jobs": exhausted_dlq,
        "retrying_jobs": retrying_dlq,
        "total_active_failures": exhausted_dlq + retrying_dlq,
    }

    overall_status = "healthy"
    if not db_ok or (settings.ENVIRONMENT == "production" and not redis_ok):
        overall_status = "critical"
    elif frag_circuit == "OPEN" or exhausted_dlq > 10:
        overall_status = "degraded"

    return {
        "success": True,
        "overall_status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot": bot_info,
        "database": db_info,
        "redis": redis_info,
        "workers": worker_info,
        "payment_providers": payment_providers,
        "fulfillment_providers": fulfillment_providers,
        "queue_depth": queue_depth,
        "failed_jobs": failed_jobs,
    }


# ================= PROBLEM ORDERS DASHBOARD (Req 9) ================= #


@router.get("/admin/orders/problematic")
async def get_problem_orders(category: Optional[str] = Query(None), limit: int = 50, session=Depends(get_db)):
    """
    Problem Orders dashboard categorizing orders:
    paid-but-not-fulfilled, stuck-processing, payment mismatch, failed fulfillment, pending refund.
    """
    now = datetime.now(timezone.utc)
    five_min_ago = now - timedelta(minutes=5)
    ten_min_ago = now - timedelta(minutes=10)

    # 1. Paid but not fulfilled (> 5 minutes)
    stmt_pnf = (
        select(Order)
        .where(
            and_(
                Order.status.in_(["paid", "processing"]),
                Order.fulfillment_status != "fulfilled",
                Order.created_at <= five_min_ago,
            )
        )
        .order_by(Order.created_at.desc())
    )

    # 2. Stuck processing (> 10 minutes)
    stmt_stuck = (
        select(Order)
        .where(
            and_(
                Order.status == "processing",
                or_(
                    Order.processing_at <= ten_min_ago,
                    and_(Order.processing_at.is_(None), Order.created_at <= ten_min_ago),
                ),
            )
        )
        .order_by(Order.created_at.desc())
    )

    # 3. Failed fulfillment
    stmt_failed = (
        select(Order)
        .where(or_(Order.status == "failed", Order.fulfillment_status == "failed", Order.fulfillment_attempts >= 3))
        .order_by(Order.created_at.desc())
    )

    # 4. Pending refund
    stmt_refund = (
        select(Order)
        .where(and_(Order.status.in_(["failed", "cancelled"]), Order.refunded_at.is_(None)))
        .order_by(Order.created_at.desc())
    )

    # Fetch counts
    res_pnf_count = await session.execute(select(func.count(Order.id)).where(stmt_pnf.whereclause))
    pnf_count = res_pnf_count.scalar() or 0

    res_stuck_count = await session.execute(select(func.count(Order.id)).where(stmt_stuck.whereclause))
    stuck_count = res_stuck_count.scalar() or 0

    res_failed_count = await session.execute(select(func.count(Order.id)).where(stmt_failed.whereclause))
    failed_count = res_failed_count.scalar() or 0

    res_refund_count = await session.execute(select(func.count(Order.id)).where(stmt_refund.whereclause))
    refund_count = res_refund_count.scalar() or 0

    # 5. Payment mismatch detection
    stmt_mismatch_orders = select(Order).where(
        and_(Order.payment_method != "balance", Order.status.in_(["paid", "completed", "processing"]))
    )
    res_mismatch_candidates = await session.execute(stmt_mismatch_orders.limit(50))
    candidate_orders = res_mismatch_candidates.scalars().all()
    mismatch_orders = []
    for o in candidate_orders:
        stmt_pay_sum = select(func.coalesce(func.sum(PaymentTransaction.amount), Decimal("0.00"))).where(
            PaymentTransaction.order_id == o.id, PaymentTransaction.status == "success"
        )
        pay_res = await session.execute(stmt_pay_sum)
        total_paid = pay_res.scalar() or Decimal("0.00")
        if total_paid != o.total_price:
            mismatch_orders.append((o, total_paid))

    mismatch_count = len(mismatch_orders)

    def _format_order(o: Order, extra_note: str = ""):
        return {
            "id": o.id,
            "order_code": o.order_code,
            "user_id": o.user_id,
            "product_type": o.product_type,
            "item_title": o.item_title,
            "amount": o.amount,
            "unit_price": float(o.unit_price or 0),
            "total_price": float(o.total_price or 0),
            "cost_price": float(o.cost_price or 0),
            "margin": float(o.margin or 0),
            "discount_amount": float(o.discount_amount or 0),
            "exchange_rate": float(o.exchange_rate or 1),
            "currency": getattr(o, "currency", "UZS") or "UZS",
            "payment_method": o.payment_method,
            "status": o.status,
            "fulfillment_status": o.fulfillment_status,
            "fulfillment_attempts": o.fulfillment_attempts,
            "fulfillment_error": o.fulfillment_error,
            "recipient_username": o.recipient_username,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "problem_detail": extra_note,
        }

    items = []
    if category == "paid_not_fulfilled":
        res = await session.execute(stmt_pnf.limit(limit))
        items = [
            _format_order(o, "To'lov qabul qilingan, lekin 5 daqiqadan beri yetkazilmagan") for o in res.scalars().all()
        ]
    elif category == "stuck_processing":
        res = await session.execute(stmt_stuck.limit(limit))
        items = [_format_order(o, "10 daqiqadan ortiq 'processing' holatida qotib qolgan") for o in res.scalars().all()]
    elif category == "payment_mismatch":
        items = [
            _format_order(o, f"To'langan summa ({paid} UZS) buyurtma summasiga ({o.total_price} UZS) mos emas")
            for (o, paid) in mismatch_orders[:limit]
        ]
    elif category == "failed_fulfillment":
        res = await session.execute(stmt_failed.limit(limit))
        items = [
            _format_order(o, o.fulfillment_error or "Yetkazib berish xatolikka uchragan") for o in res.scalars().all()
        ]
    elif category == "pending_refund":
        res = await session.execute(stmt_refund.limit(limit))
        items = [
            _format_order(o, "Bekor qilingan, lekin mablag' hali foydalanuvchiga qaytarilmagan")
            for o in res.scalars().all()
        ]
    else:
        res_p = await session.execute(stmt_pnf.limit(10))
        items.extend([_format_order(o, "To'langan, ammo yetkazilmagan") for o in res_p.scalars().all()])
        res_f = await session.execute(stmt_failed.limit(10))
        items.extend([_format_order(o, "Yetkazish xatosi") for o in res_f.scalars().all()])

    return {
        "success": True,
        "counts": {
            "paid_not_fulfilled": pnf_count,
            "stuck_processing": stuck_count,
            "payment_mismatch": mismatch_count,
            "failed_fulfillment": failed_count,
            "pending_refund": refund_count,
            "total_problematic": pnf_count + stuck_count + mismatch_count + failed_count + refund_count,
        },
        "orders": items,
    }


@router.post("/admin/orders/{order_id}/retry-fulfillment")
async def retry_order_fulfillment(order_id: int, action: ReasonedAdminAction, session=Depends(get_db)):
    """Triggers an immediate automated fulfillment retry for a problem order."""
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

    order.fulfillment_status = "processing"
    order.status = "processing"
    await session.flush()

    res = await fulfillment_service.fulfill_order_automated(session=session, order_id=order_id)
    return {"success": res.get("success", False), "fulfilled": res.get("fulfilled", False), "result": res}


@router.post("/admin/orders/{order_id}/manual-fulfill")
async def manual_fulfill_order(order_id: int, action: ReasonedAdminAction, session=Depends(get_db)):
    """Admin manually marks a problematic order as fulfilled with required reason."""
    order = await order_service.transition_order_status(
        session=session, order_id=order_id, new_status_raw="completed", reason=f"Qo'lda bajarildi: {action.reason}"
    )
    order.fulfillment_status = "fulfilled"
    order.fulfillment_error = None
    await session.commit()
    return {"success": True, "order_code": order.order_code, "status": order.status}


# ================= ADMIN PRICE CHANGE PREVIEW (Req 17) ================= #


@router.post("/admin/pricing/preview")
async def preview_price_changes(req: PricePreviewRequest, session=Depends(get_db)):
    """
    Simulates pricing changes across all product types (Stars, Premium, Gifts)
    before applying changes to production (Req 17).
    """
    current_pricing = await session.get(PricingSetting, 1)

    sim_ton_rate = req.ton_rate_uzs or (current_pricing.ton_rate_uzs if current_pricing else Decimal("14800.00"))
    sim_margin = req.margin_percent or (current_pricing.margin_percent if current_pricing else Decimal("15.00"))
    sim_star_cost_ton = req.stars_cost_ton or (current_pricing.stars_cost_ton if current_pricing else Decimal("0.0021"))
    sim_star_unit_price = req.star_unit_price_uzs or (
        current_pricing.star_unit_price_uzs if current_pricing else Decimal("180.00")
    )

    sim_pricing = PricingSetting(
        id=999,
        ton_rate_uzs=sim_ton_rate,
        margin_percent=sim_margin,
        stars_cost_ton=sim_star_cost_ton,
        star_unit_price_uzs=sim_star_unit_price,
        minimum_margin=Decimal("5.00"),
        maximum_discount=Decimal("30.00"),
        minimum_price=Decimal("1000.00"),
        premium_prices_json=current_pricing.premium_prices_json if current_pricing else None,
        gifts_json=current_pricing.gifts_json if current_pricing else None,
    )

    items_to_test = [
        {"category": "stars", "sku": "stars_100", "title": "100 Telegram Stars", "amount": 100},
        {"category": "stars", "sku": "stars_250", "title": "250 Telegram Stars", "amount": 250},
        {"category": "stars", "sku": "stars_500", "title": "500 Telegram Stars", "amount": 500},
        {"category": "stars", "sku": "stars_1000", "title": "1,000 Telegram Stars", "amount": 1000},
        {"category": "premium", "sku": "premium_3m", "title": "Telegram Premium (3 oy)", "months": 3},
        {"category": "premium", "sku": "premium_6m", "title": "Telegram Premium (6 oy)", "months": 6},
        {"category": "premium", "sku": "premium_12m", "title": "Telegram Premium (12 oy)", "months": 12},
    ]

    comparisons = []
    for item in items_to_test:
        if item["category"] == "stars":
            curr_info = pricing_service.calculate_stars_price(item["amount"], current_pricing)
            prev_info = pricing_service.calculate_stars_price(item["amount"], sim_pricing)
            curr_p = float(curr_info["total_price_decimal"])
            prev_p = float(prev_info["total_price_decimal"])
        elif item["category"] == "premium":
            curr_info = pricing_service.calculate_premium_price(item["months"], current_pricing)
            prev_info = pricing_service.calculate_premium_price(item["months"], sim_pricing)
            curr_p = float(curr_info["total_price_decimal"])
            prev_p = float(prev_info["total_price_decimal"])
        else:
            continue

        diff = prev_p - curr_p
        diff_pct = round((diff / curr_p * 100), 2) if curr_p > 0 else 0.0

        comparisons.append(
            {
                "category": item["category"],
                "sku": item["sku"],
                "title": item["title"],
                "current_price_uzs": curr_p,
                "preview_price_uzs": prev_p,
                "diff_uzs": diff,
                "diff_percent": diff_pct,
                "formatted_current": f"{int(curr_p):,} UZS".replace(",", " "),
                "formatted_preview": f"{int(prev_p):,} UZS".replace(",", " "),
            }
        )

    return {
        "success": True,
        "parameters": {
            "ton_rate_uzs": float(sim_ton_rate),
            "margin_percent": float(sim_margin),
            "star_unit_price_uzs": float(sim_star_unit_price),
        },
        "preview": comparisons,
    }


# ================= ORDER TIMELINE & RECEIPT (Req 13 & Req 16) ================= #


@router.get("/orders/{order_id_or_code}/timeline")
async def get_order_status_timeline(order_id_or_code: str, session=Depends(get_db)):
    """Returns chronological audit timeline for the specified order (Req 13)."""
    timeline = await order_service.get_order_timeline(session, order_id_or_code)
    if not timeline:
        order = await order_service.get_order_by_id_or_code(session, order_id_or_code)
        if not order:
            raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
        return {
            "success": True,
            "order_code": order.order_code,
            "timeline": [
                {
                    "id": 0,
                    "from_status": None,
                    "to_status": order.status,
                    "actor": "SYSTEM",
                    "note": f"Buyurtma holati: {order.status}",
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                }
            ],
        }

    return {
        "success": True,
        "order_code": timeline[0].order_code,
        "timeline": [
            {
                "id": t.id,
                "from_status": t.from_status,
                "to_status": t.to_status,
                "actor": t.actor,
                "note": t.note,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in timeline
        ],
    }


@router.get("/orders/{order_id_or_code}/receipt")
async def get_order_receipt(order_id_or_code: str, session=Depends(get_db)):
    """
    Returns immutable financial receipt snapshot for the specified order.
    Never recalculates prices from live settings (Req 10, Req 11 & Req 16).
    """
    order = await order_service.get_order_by_id_or_code(session, order_id_or_code)
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

    stmt_tx = select(PaymentTransaction).where(PaymentTransaction.order_id == order.id)
    res_tx = await session.execute(stmt_tx)
    pay_tx = res_tx.scalars().first()

    return {
        "success": True,
        "receipt": {
            "receipt_number": order.order_code,
            "order_id": order.id,
            "date": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "user_id": order.user_id,
            "product": {"product_type": order.product_type, "item_title": order.item_title, "quantity": order.amount},
            "financials": {
                "unit_price_uzs": float(order.unit_price or 0),
                "cost_price_uzs": float(order.cost_price or 0),
                "margin_uzs": float(order.margin or 0),
                "discount_amount_uzs": float(order.discount_amount or 0),
                "promo_code": order.promo_code,
                "exchange_rate": float(order.exchange_rate or 1),
                "total_price_uzs": float(order.total_price or 0),
                "currency": getattr(order, "currency", "UZS") or "UZS",
            },
            "payment": {
                "method": order.payment_method,
                "status": order.status,
                "provider_tx_id": pay_tx.provider_transaction_id if pay_tx else None,
                "provider": pay_tx.provider if pay_tx else order.payment_method,
            },
            "delivery": {
                "recipient_username": order.recipient_username,
                "fulfillment_status": order.fulfillment_status,
                "tx_hash": order.fragment_tx_hash,
            },
        },
    }


# ================= BUY AGAIN HELPER (Req 14) ================= #


@router.get("/orders/{order_id_or_code}/buy-again-details")
async def get_buy_again_details(order_id_or_code: str, session=Depends(get_db)):
    """
    Safely retrieves product and recipient details from a previous order,
    and calculates current authoritative live pricing (Req 14).
    """
    order = await order_service.get_order_by_id_or_code(session, order_id_or_code)
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

    current_price_info = await pricing_service.get_authoritative_price(
        session=session, product_type=order.product_type, amount=order.amount, item_title=order.item_title
    )

    return {
        "success": True,
        "product_type": order.product_type,
        "item_title": order.item_title,
        "amount": order.amount,
        "recipient_username": order.recipient_username,
        "current_total_price_uzs": float(current_price_info["total_price_decimal"]),
        "formatted_price": current_price_info.get(
            "formatted_price", f"{int(current_price_info['total_price_decimal']):,} UZS"
        ),
        "historical_paid_price_uzs": float(order.total_price),
        "currency": "UZS",
    }


# ================= SAVED RECIPIENTS (Req 15) ================= #


@router.get("/recipients")
async def list_saved_recipients(user_id: int = Query(...), session=Depends(get_db)):
    """Lists saved favorite recipient usernames for quick checkout selection (Req 15)."""
    stmt = select(SavedRecipient).where(SavedRecipient.user_id == user_id).order_by(SavedRecipient.created_at.desc())
    res = await session.execute(stmt)
    items = res.scalars().all()
    return {
        "success": True,
        "recipients": [
            {
                "id": r.id,
                "recipient_username": r.recipient_username,
                "label": r.label,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
    }


@router.post("/recipients")
async def add_saved_recipient(req: SavedRecipientCreate, session=Depends(get_db)):
    """Saves a new favorite recipient for the user (Req 15)."""
    clean_username = req.recipient_username.strip().lstrip("@")
    if not clean_username:
        raise HTTPException(status_code=400, detail="Qabul qiluvchi username bo'sh bo'lishi mumkin emas.")

    stmt = select(SavedRecipient).where(
        SavedRecipient.user_id == req.user_id, SavedRecipient.recipient_username == clean_username
    )
    res = await session.execute(stmt)
    existing = res.scalars().first()
    if existing:
        if req.label:
            existing.label = req.label
            await session.commit()
        return {"success": True, "recipient_id": existing.id, "message": "Qabul qiluvchi allaqachon mavjud"}

    rec = SavedRecipient(user_id=req.user_id, recipient_username=clean_username, label=req.label or clean_username)
    session.add(rec)
    await session.commit()
    await session.refresh(rec)
    return {"success": True, "recipient_id": rec.id}


@router.delete("/recipients/{recipient_id}")
async def delete_saved_recipient(recipient_id: int, user_id: int = Query(...), session=Depends(get_db)):
    """Removes a saved recipient for the user (Req 15)."""
    rec = await session.get(SavedRecipient, recipient_id)
    if not rec or rec.user_id != user_id:
        raise HTTPException(status_code=404, detail="Qabul qiluvchi topilmadi.")
    await session.delete(rec)
    await session.commit()
    return {"success": True, "message": "Qabul qiluvchi o'chirildi."}
