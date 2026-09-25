from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.core.correlation import get_correlation_id
from app.core.database import AsyncSessionLocal
from app.core.exceptions import GiftHubException, InsufficientBalanceError
from app.core.logging import get_logger
from app.core.security import Permission
from app.models.audit import AdminAuditLog
from app.models.catalog import CatalogProduct
from app.models.dlq import DLQStatus, FailedJob
from app.models.feature_flags import FeatureFlag
from app.models.provider import ProviderHealth, ProviderStatus
from app.models.reconciliation import ReconciliationDiscrepancy, ReconciliationReport
from app.services.catalog.service import catalog_service
from app.services.dlq.service import dlq_service
from app.services.feature_flags.service import feature_flag_service
from app.services.orders.service import order_service
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
    product_type: str # stars, premium, gift, service
    quantity: int = 1
    recipient_username: Optional[str] = None
    promo_code: Optional[str] = None
    price_lock_id: Optional[str] = None
    payment_method: str = "balance"


class ReasonedAdminAction(BaseModel):
    reason: str = Field(..., min_length=5, description="Auditing reason is mandatory for sensitive actions")
    notes: Optional[str] = None


class ProviderStatusUpdate(ReasonedAdminAction):
    status: str # healthy, degraded, disabled


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
async def get_public_catalog(
    category: Optional[str] = None,
    session=Depends(get_db)
):
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
                "display_order": p.display_order
            }
            for p in products
        ]
    }


# ================= CHECKOUT WITH IDEMPOTENCY (Req 7 & Req 8) ================= #

@router.post("/orders/checkout")
async def create_checkout_order(
    req: CheckoutRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session=Depends(get_db)
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
            correlation_id=cid
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
                "correlation_id": cid
            }
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
        "discrepancies_found": report.discrepancies_count
    }


@router.get("/admin/reconciliation/discrepancies")
async def list_discrepancies(
    is_resolved: Optional[bool] = Query(None),
    limit: int = 50,
    session=Depends(get_db)
):
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
                "created_at": d.created_at.isoformat() if d.created_at else None
            }
            for d in items
        ]
    }


@router.post("/admin/reconciliation/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(
    discrepancy_id: int,
    action: ReasonedAdminAction,
    session=Depends(get_db)
):
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
    job_status: Optional[str] = Query(None, alias="status"),
    limit: int = 50,
    session=Depends(get_db)
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
                "created_at": j.created_at.isoformat() if j.created_at else None
            }
            for j in jobs
        ]
    }


@router.post("/admin/dlq/{job_id}/retry")
async def retry_dlq_job(
    job_id: int,
    session=Depends(get_db)
):
    job = await dlq_service.mark_retrying(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="DLQ job topilmadi.")
    return {"success": True, "message": f"Job #{job_id} qayta urinish navbatiga qo'yildi."}


@router.post("/admin/dlq/{job_id}/resolve")
async def resolve_dlq_job(
    job_id: int,
    action: ReasonedAdminAction,
    session=Depends(get_db)
):
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
        result.append({
            "provider_name": p.provider_name,
            "status": p.status,
            "circuit_state": st["state"],
            "failure_count": p.failure_count,
            "success_count": p.success_count,
            "consecutive_failures": st["consecutive_failures"],
            "disabled_reason": p.disabled_reason
        })
    return {"success": True, "providers": result}


@router.post("/admin/providers/{provider_name}/status")
async def update_provider_status(
    provider_name: str,
    action: ProviderStatusUpdate,
    session=Depends(get_db)
):
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
        created_at=now
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
        "flags": [
            {
                "name": f.name,
                "is_enabled": f.is_enabled,
                "description": f.description
            }
            for f in flags
        ]
    }


@router.post("/admin/feature-flags/{name}")
async def set_feature_flag(
    name: str,
    req: FeatureFlagUpdate,
    session=Depends(get_db)
):
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
                "display_order": p.display_order
            }
            for p in products
        ]
    }


@router.post("/admin/catalog")
async def create_catalog_item(
    item: CatalogProductCreate,
    session=Depends(get_db)
):
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
        display_order=item.display_order
    )
    return {"success": True, "product_id": prod.id}
