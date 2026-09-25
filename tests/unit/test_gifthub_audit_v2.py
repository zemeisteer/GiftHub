from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import get_db as v1_get_db
from app.core.database import get_db
from app.models.order import Order, OrderStatusHistory
from app.models.recipient import SavedRecipient
from app.models.user import User
from app.services.orders.service import order_service
from app.web.server import app


@pytest.mark.asyncio
async def test_public_order_code_format_and_lookup():
    code = order_service.generate_order_code()
    assert code.startswith("GH-")
    assert len(code) == 9  # "GH-" + 6 digits


@pytest.mark.asyncio
async def test_order_financial_snapshots_and_history(db_session: AsyncSession, sample_user: User):
    """Verifies Req 10, Req 11, Req 12, Req 13, Req 18."""
    order, bonus, referrer = await order_service.create_order(
        session=db_session,
        user_id=sample_user.id,
        product_type="stars",
        item_title="100 Telegram Stars",
        amount=100,
        recipient_username="friend_user",
        payment_method="click"
    )

    # 1. Public ID format
    assert order.order_code.startswith("GH-")
    assert order.id is not None

    # 2. Immutable financial snapshot
    assert order.currency == "UZS"
    assert order.unit_price is not None
    assert order.cost_price is not None
    assert order.margin is not None
    assert order.total_price is not None
    assert order.exchange_rate is not None

    # 3. Order status history created
    timeline = await order_service.get_order_timeline(db_session, order.order_code)
    assert len(timeline) >= 1
    assert timeline[0].to_status == "created"
    assert timeline[0].order_code == order.order_code

    # 4. State transition appends history
    await order_service.transition_order_status(
        session=db_session,
        order_id=order.id,
        new_status_raw="paid",
        actor="PAYMENT_GATEWAY",
        reason="Click to'lovi muvaffaqiyatli o'tdi"
    )
    timeline_updated = await order_service.get_order_timeline(db_session, order.order_code)
    assert len(timeline_updated) == 2
    assert timeline_updated[-1].from_status == "created"
    assert timeline_updated[-1].to_status == "paid"
    assert timeline_updated[-1].actor == "PAYMENT_GATEWAY"


@pytest.mark.asyncio
async def test_saved_recipients_api(db_session: AsyncSession, sample_user: User):
    """Verifies Req 15."""
    app.dependency_overrides[v1_get_db] = lambda: db_session
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Add saved recipient
            resp = await client.post("/api/v1/recipients", json={
                "user_id": sample_user.id,
                "recipient_username": "my_best_friend",
                "label": "Eng yaxshi do'stim"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            rec_id = data["recipient_id"]

            # List saved recipients
            list_resp = await client.get(f"/api/v1/recipients?user_id={sample_user.id}")
            assert list_resp.status_code == 200
            recipients = list_resp.json()["recipients"]
            assert len(recipients) == 1
            assert recipients[0]["recipient_username"] == "my_best_friend"

            # Delete saved recipient
            del_resp = await client.delete(f"/api/v1/recipients/{rec_id}?user_id={sample_user.id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["success"] is True
    finally:
        app.dependency_overrides.pop(v1_get_db, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_order_receipt_and_buy_again_api(db_session: AsyncSession, sample_user: User):
    """Verifies Req 14 & Req 16."""
    order, _, _ = await order_service.create_order(
        session=db_session,
        user_id=sample_user.id,
        product_type="stars",
        item_title="50 Telegram Stars",
        amount=50,
        recipient_username="test_target",
        payment_method="balance"
    )
    order.status = "completed"
    order.fulfillment_status = "fulfilled"
    order.fragment_tx_hash = "mock_tx_hash_12345"
    await db_session.commit()

    app.dependency_overrides[v1_get_db] = lambda: db_session
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Receipt
            rcp_resp = await client.get(f"/api/v1/orders/{order.order_code}/receipt")
            assert rcp_resp.status_code == 200
            rcp_data = rcp_resp.json()
            assert rcp_data["success"] is True
            receipt = rcp_data["receipt"]
            assert receipt["receipt_number"] == order.order_code
            assert receipt["financials"]["currency"] == "UZS"
            assert receipt["delivery"]["recipient_username"] == "test_target"
            assert receipt["delivery"]["tx_hash"] == "mock_tx_hash_12345"

            # 2. Buy Again Details
            ba_resp = await client.get(f"/api/v1/orders/{order.order_code}/buy-again-details")
            assert ba_resp.status_code == 200
            ba_data = ba_resp.json()
            assert ba_data["success"] is True
            assert ba_data["product_type"] == "stars"
            assert ba_data["amount"] == 50
            assert ba_data["recipient_username"] == "test_target"
            assert ba_data["current_total_price_uzs"] > 0
            assert ba_data["currency"] == "UZS"
    finally:
        app.dependency_overrides.pop(v1_get_db, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_system_health_and_problematic_orders_api(db_session: AsyncSession):
    """Verifies Req 8 & Req 9."""
    app.dependency_overrides[v1_get_db] = lambda: db_session
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. System Health
            health_resp = await client.get("/api/v1/admin/health/system")
            assert health_resp.status_code == 200
            h_data = health_resp.json()
            assert h_data["success"] is True
            assert "database" in h_data
            assert "redis" in h_data
            assert "workers" in h_data
            assert "payment_providers" in h_data
            assert "fulfillment_providers" in h_data
            assert "queue_depth" in h_data

            # 2. Problematic Orders
            prob_resp = await client.get("/api/v1/admin/orders/problematic")
            assert prob_resp.status_code == 200
            p_data = prob_resp.json()
            assert p_data["success"] is True
            assert "counts" in p_data
            assert "paid_not_fulfilled" in p_data["counts"]
            assert "stuck_processing" in p_data["counts"]
            assert "payment_mismatch" in p_data["counts"]
            assert "failed_fulfillment" in p_data["counts"]
            assert "pending_refund" in p_data["counts"]
    finally:
        app.dependency_overrides.pop(v1_get_db, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_price_preview_simulation(db_session: AsyncSession):
    """Verifies Req 17."""
    app.dependency_overrides[v1_get_db] = lambda: db_session
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/admin/pricing/preview", json={
                "margin_percent": 25.0,
                "star_unit_price_uzs": 190.0,
                "ton_rate_uzs": 15000.0
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "preview" in data
            assert len(data["preview"]) > 0
            first_item = data["preview"][0]
            assert "current_price_uzs" in first_item
            assert "preview_price_uzs" in first_item
            assert "diff_uzs" in first_item
            assert "diff_percent" in first_item
    finally:
        app.dependency_overrides.pop(v1_get_db, None)
        app.dependency_overrides.pop(get_db, None)
