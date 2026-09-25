import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, or_, and_

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import GiftHubException
from app.core.logging import get_logger
from app.core.security import Permission
from app.models import (
    BroadcastDraft,
    ChannelRequirement,
    FragmentSetting,
    Order,
    OrderStatus,
    PaymentCard,
    PaymentSetting,
    PromoCode,
    ReferralSetting,
    SupportTicket,
    TicketMessage,
    User,
)
from app.services.fulfillment.service import fulfillment_service
from app.services.orders.service import order_service
from app.services.wallet.service import wallet_service
from app.utils.notifications import (
    send_admin_order_alert,
    send_order_created_notification,
    send_order_status_update_notification,
)
from app.web.auth import get_current_admin, require_permission
from app.web.state import get_bot
from database import queries

logger = get_logger(__name__)

router = APIRouter()

@router.get("/api/admin/stats")
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


