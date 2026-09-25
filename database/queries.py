import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import String, delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GiftHubException, OrderNotFoundError
from app.core.logging import get_logger
from app.models import (
    AdminAuditLog,
    BroadcastDraft,
    ChannelRequirement,
    CustomService,
    FragmentSetting,
    Order,
    OrderStatus,
    PaymentCard,
    PaymentSetting,
    PricingSetting,
    PromoCode,
    PromoCodeUsage,
    PromoRedemption,
    ReferralSetting,
    Transaction,
    User,
    UserJoinRequest,
    WalletTransaction,
)
from app.models.base import utc_now
from app.services.orders.service import order_service
from app.services.pricing.service import pricing_service
from app.services.promotions.service import promotion_service
from app.services.referrals.service import referral_service
from app.services.wallet.service import wallet_service

logger = get_logger(__name__)


# ================= USER QUERIES ================= #


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    first_name: str,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    photo_url: Optional[str] = None,
    referrer_id: Optional[int] = None,
) -> User:
    user = await session.get(User, user_id)
    if not user:
        valid_referrer = None
        if referrer_id and referrer_id != user_id:
            ref_user = await session.get(User, referrer_id)
            if ref_user:
                valid_referrer = referrer_id
                ref_user.referrals_count += 1

        user = User(
            id=user_id,
            first_name=first_name,
            last_name=last_name or "",
            username=username,
            photo_url=photo_url,
            referrer_id=valid_referrer,
            balance=Decimal("0.00"),
            referral_earnings=Decimal("0.00"),
            referrals_count=0,
            role="user",
            is_blocked=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        updated = False
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            updated = True
        if last_name is not None and user.last_name != last_name:
            user.last_name = last_name
            updated = True
        if username is not None and user.username != username:
            user.username = username
            updated = True
        if photo_url is not None and user.photo_url != photo_url:
            user.photo_url = photo_url
            updated = True
        if updated:
            user.updated_at = utc_now()
            await session.commit()
    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    clean_username = username.lstrip("@").strip()
    res = await session.execute(select(User).where(func.lower(User.username) == clean_username.lower()))
    return res.scalars().first()


async def list_users(
    session: AsyncSession, search: Optional[str] = None, limit: int = 50, offset: int = 0
) -> List[User]:
    query = select(User).order_by(desc(User.created_at))
    if search:
        search_term = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(User.first_name).like(search_term)
            | func.lower(User.username).like(search_term)
            | User.id.cast(String).like(search_term)
        )
    res = await session.execute(query.offset(offset).limit(limit))
    return list(res.scalars().all())


async def update_user_balance(
    session: AsyncSession,
    user_id: int,
    amount: float,
    tx_type: str,
    method: str = "balance",
    note: Optional[str] = None,
) -> Optional[User]:
    """
    Safely mutates user balance by routing through the immutable wallet ledger.
    """
    dec_amount = Decimal(str(amount))
    if dec_amount > Decimal("0.00"):
        user, tx = await wallet_service.credit_balance(
            session=session, user_id=user_id, amount=dec_amount, tx_type=tx_type, reference_type=method, note=note
        )
    elif dec_amount < Decimal("0.00"):
        user, tx = await wallet_service.debit_balance(
            session=session, user_id=user_id, amount=abs(dec_amount), tx_type=tx_type, reference_type=method, note=note
        )
    else:
        user = await session.get(User, user_id)

    await session.commit()
    if user:
        await session.refresh(user)
    return user


# ================= PRICING QUERIES ================= #


async def get_pricing(session: AsyncSession) -> PricingSetting:
    pricing = await session.get(PricingSetting, 1)
    if not pricing:
        pricing = PricingSetting(
            id=1,
            stars_cost_ton=Decimal("0.0021"),
            ton_rate_uzs=Decimal("14800.00"),
            margin_percent=Decimal("15.00"),
            star_unit_price_uzs=Decimal("180.00"),
        )
        session.add(pricing)
        await session.commit()
        await session.refresh(pricing)
    return pricing


async def update_pricing(
    session: AsyncSession,
    stars_cost_ton: float,
    ton_rate_uzs: float,
    margin_percent: float,
    star_unit_price_uzs: Optional[float] = None,
    stars_discounts_json: Optional[str] = None,
    premium_prices_json: Optional[str] = None,
    gifts_json: Optional[str] = None,
) -> PricingSetting:
    pricing = await get_pricing(session)
    pricing.stars_cost_ton = Decimal(str(stars_cost_ton))
    pricing.ton_rate_uzs = Decimal(str(ton_rate_uzs))
    pricing.margin_percent = Decimal(str(margin_percent))
    if star_unit_price_uzs is not None and star_unit_price_uzs > 0:
        pricing.star_unit_price_uzs = Decimal(str(star_unit_price_uzs))
    if stars_discounts_json is not None:
        pricing.stars_discounts_json = stars_discounts_json
    if premium_prices_json is not None:
        pricing.premium_prices_json = premium_prices_json
    if gifts_json is not None:
        pricing.gifts_json = gifts_json
    pricing.updated_at = utc_now()
    await session.commit()
    await session.refresh(pricing)
    return pricing


def calculate_stars_price(amount: int, pricing: Optional[PricingSetting] = None) -> Dict[str, Any]:
    return pricing_service.calculate_stars_price(amount, pricing)


# ================= ORDERS & TRANSACTIONS ================= #


async def create_order(
    session: AsyncSession,
    user_id: int,
    product_type: str,
    item_title: str,
    amount: int,
    total_price: Optional[float] = None,
    cost_price: Optional[float] = None,
    recipient_username: Optional[str] = None,
    status: Optional[str] = None,
    promo_code: Optional[str] = None,
    price_lock_id: Optional[str] = None,
) -> Tuple[Order, Decimal, Optional[User]]:
    """
    Creates order through OrderService with server-authoritative pricing and atomic wallet deduction.
    """
    return await order_service.create_order(
        session=session,
        user_id=user_id,
        product_type=product_type,
        item_title=item_title,
        amount=amount,
        recipient_username=recipient_username,
        promo_code_str=promo_code,
        price_lock_id=price_lock_id,
    )


async def process_referral_reward(session: AsyncSession, buyer: User, purchase_amount: float):
    return await referral_service.process_order_referral_reward(
        session=session, order_id=0, buyer_id=buyer.id, purchase_amount=Decimal(str(purchase_amount))
    )


async def list_user_orders(session: AsyncSession, user_id: int, status: Optional[str] = None) -> List[Order]:
    query = select(Order).where(Order.user_id == user_id).order_by(desc(Order.created_at))
    if status and status != "all":
        norm = OrderStatus.COMPLETED if status == "done" else (OrderStatus.CANCELLED if status == "cancel" else status)
        query = query.where(Order.status.in_([status, norm]))
    res = await session.execute(query)
    return list(res.scalars().all())


async def list_all_orders(
    session: AsyncSession,
    search: Optional[str] = None,
    status: Optional[str] = None,
    product_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Order]:
    query = select(Order).order_by(desc(Order.created_at))
    if search:
        s = f"%{search.strip().lower()}%"
        query = query.where(
            Order.order_code.like(s) | func.lower(Order.item_title).like(s) | Order.user_id.cast(String).like(s)
        )
    if status and status != "all":
        norm = OrderStatus.COMPLETED if status == "done" else (OrderStatus.CANCELLED if status == "cancel" else status)
        query = query.where(Order.status.in_([status, norm]))
    if product_type and product_type != "all":
        query = query.where(Order.product_type == product_type)

    res = await session.execute(query.offset(offset).limit(limit))
    return list(res.scalars().all())


async def update_order_status(
    session: AsyncSession,
    order_id: int,
    new_status: str,
    payload: Optional[str] = None,
    admin_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> Optional[Order]:
    return await order_service.transition_order_status(
        session=session, order_id=order_id, new_status_raw=new_status, admin_id=admin_id, reason=reason, payload=payload
    )


# ================= MANDATORY CHANNELS ================= #


async def list_channels(session: AsyncSession, active_only: bool = False) -> List[ChannelRequirement]:
    query = select(ChannelRequirement).order_by(ChannelRequirement.id)
    if active_only:
        query = query.where(ChannelRequirement.is_active == True, ChannelRequirement.is_detected == False)
    res = await session.execute(query)
    return list(res.scalars().all())


async def add_or_update_channel(
    session: AsyncSession,
    username_or_link: str,
    title: str,
    req_type: str = "ordinary",
    chat_id: Optional[int] = None,
    is_detected: bool = False,
    is_active: Optional[bool] = None,
) -> ChannelRequirement:
    res = await session.execute(
        select(ChannelRequirement).where(ChannelRequirement.username_or_link == username_or_link)
    )
    ch = res.scalars().first()
    active_flag = (not is_detected) if is_active is None else is_active
    if ch:
        ch.title = title
        ch.req_type = req_type
        if chat_id:
            ch.chat_id = chat_id
        ch.is_active = active_flag
        ch.is_detected = is_detected
    else:
        ch = ChannelRequirement(
            chat_id=chat_id,
            username_or_link=username_or_link,
            title=title,
            req_type=req_type,
            is_active=active_flag,
            is_detected=is_detected,
        )
        session.add(ch)
    await session.commit()
    await session.refresh(ch)
    return ch


async def confirm_detected_channel(
    session: AsyncSession, channel_id: int, req_type: str = "ordinary"
) -> Optional[ChannelRequirement]:
    ch = await session.get(ChannelRequirement, channel_id)
    if ch:
        ch.is_detected = False
        ch.is_active = True
        ch.req_type = req_type
        await session.commit()
        await session.refresh(ch)
    return ch


async def delete_channel(session: AsyncSession, channel_id: int):
    ch = await session.get(ChannelRequirement, channel_id)
    if ch:
        await session.delete(ch)
        await session.commit()


async def update_channel_type(session: AsyncSession, channel_id: int, req_type: str) -> Optional[ChannelRequirement]:
    ch = await session.get(ChannelRequirement, channel_id)
    if ch:
        ch.req_type = req_type
        await session.commit()
        await session.refresh(ch)
    return ch


async def record_user_join_request(session: AsyncSession, user_id: int, chat_id: int):
    res = await session.execute(
        select(UserJoinRequest).where(UserJoinRequest.user_id == user_id, UserJoinRequest.chat_id == chat_id)
    )
    if not res.scalars().first():
        req = UserJoinRequest(user_id=user_id, chat_id=chat_id)
        session.add(req)
        await session.commit()


async def has_user_join_request(session: AsyncSession, user_id: int, chat_id: int) -> bool:
    res = await session.execute(
        select(UserJoinRequest).where(UserJoinRequest.user_id == user_id, UserJoinRequest.chat_id == chat_id)
    )
    return res.scalars().first() is not None


# ================= ADMINS & AUDIT LOGS ================= #


async def log_admin_action(
    session: AsyncSession,
    admin_id: int,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[str] = None,
    admin_username: Optional[str] = None,
):
    log = AdminAuditLog(
        admin_id=admin_id,
        admin_username=admin_username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
        created_at=utc_now(),
    )
    session.add(log)
    await session.commit()


async def list_audit_logs(session: AsyncSession, limit: int = 50) -> List[AdminAuditLog]:
    res = await session.execute(select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at)).limit(limit))
    return list(res.scalars().all())


async def list_admins(session: AsyncSession) -> List[User]:
    res = await session.execute(select(User).where(User.role != "user").order_by(desc(User.created_at)))
    return list(res.scalars().all())


async def set_user_role(session: AsyncSession, user_id: int, new_role: str) -> Optional[User]:
    user = await session.get(User, user_id)
    if user:
        user.role = new_role
        user.updated_at = utc_now()
        await session.commit()
        await session.refresh(user)
    return user


# ================= BROADCAST AUDIENCE ================= #


async def get_broadcast_recipients(session: AsyncSession, segment: str = "all") -> List[int]:
    if segment == "all":
        res = await session.execute(select(User.id).where(User.is_blocked == False))
        return list(res.scalars().all())
    elif segment == "non_buyers":
        subq = select(Order.user_id).distinct()
        res = await session.execute(select(User.id).where(User.id.not_in(subq), User.is_blocked == False))
        return list(res.scalars().all())
    elif segment == "active":
        subq = select(Order.user_id).where(Order.status.in_([OrderStatus.COMPLETED, "done"])).distinct()
        res = await session.execute(select(User.id).where(User.id.in_(subq), User.is_blocked == False))
        return list(res.scalars().all())
    elif segment == "referral":
        res = await session.execute(select(User.id).where(User.referrer_id.isnot(None), User.is_blocked == False))
        return list(res.scalars().all())
    return []


# ================= PROMO CODES ================= #


async def list_promo_codes(session: AsyncSession) -> List[PromoCode]:
    res = await session.execute(select(PromoCode).order_by(desc(PromoCode.created_at)))
    return list(res.scalars().all())


async def create_promo_code(
    session: AsyncSession,
    code: str,
    reward_type: str = "discount_percent",
    reward_value: float = 10.0,
    max_uses: int = 100,
    min_order_amount: float = 0.0,
    is_active: bool = True,
    expires_at: Optional[datetime] = None,
) -> PromoCode:
    clean_code = code.strip().upper()
    existing = await session.execute(select(PromoCode).where(PromoCode.code == clean_code))
    if existing.scalars().first():
        raise ValueError("Bu promo-kod allaqachon mavjud!")

    promo = PromoCode(
        code=clean_code,
        reward_type=reward_type,
        reward_value=Decimal(str(reward_value)),
        max_uses=max_uses,
        current_uses=0,
        min_order_amount=Decimal(str(min_order_amount)),
        is_active=is_active,
        expires_at=expires_at,
        created_at=utc_now(),
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def delete_promo_code(session: AsyncSession, promo_id: int) -> bool:
    promo = await session.get(PromoCode, promo_id)
    if promo:
        await session.delete(promo)
        await session.commit()
        return True
    return False


async def toggle_promo_code(session: AsyncSession, promo_id: int) -> Optional[PromoCode]:
    promo = await session.get(PromoCode, promo_id)
    if promo:
        promo.is_active = not promo.is_active
        await session.commit()
        await session.refresh(promo)
    return promo


async def apply_promo_code(session: AsyncSession, code: str, user_id: int, order_total: float = 0.0) -> Dict[str, Any]:
    return await promotion_service.apply_promo_code(
        session=session, code_str=code, user_id=user_id, order_total=Decimal(str(order_total))
    )


# ================= FRAGMENT SETTINGS & FULFILLMENT ================= #


async def get_fragment_settings(session: AsyncSession) -> FragmentSetting:
    setting = await session.get(FragmentSetting, 1)
    if not setting:
        setting = FragmentSetting(
            id=1,
            is_auto_buy=True,
            ton_wallet_address="",
            ton_wallet_mnemonic="",
            tonapi_key="",
            network="mainnet",
            min_ton_balance=Decimal("1.0000"),
            simulation_mode=False,
        )
        session.add(setting)
        await session.commit()
        await session.refresh(setting)
    return setting


async def update_fragment_settings(
    session: AsyncSession,
    is_auto_buy: Optional[bool] = None,
    ton_wallet_address: Optional[str] = None,
    ton_wallet_mnemonic: Optional[str] = None,
    tonapi_key: Optional[str] = None,
    network: Optional[str] = None,
    min_ton_balance: Optional[float] = None,
    simulation_mode: Optional[bool] = None,
) -> FragmentSetting:
    setting = await get_fragment_settings(session)
    if is_auto_buy is not None:
        setting.is_auto_buy = is_auto_buy
    if ton_wallet_address is not None:
        setting.ton_wallet_address = ton_wallet_address.strip()
    if ton_wallet_mnemonic is not None:
        setting.ton_wallet_mnemonic = ton_wallet_mnemonic.strip()
    if tonapi_key is not None:
        setting.tonapi_key = tonapi_key.strip()
    if network is not None:
        setting.network = network.strip().lower()
    if min_ton_balance is not None:
        setting.min_ton_balance = Decimal(str(min_ton_balance))
    if simulation_mode is not None:
        setting.simulation_mode = simulation_mode
    setting.updated_at = utc_now()
    await session.commit()
    return setting


async def update_order_fulfillment(
    session: AsyncSession,
    order_id: int,
    fulfillment_status: str,
    status: Optional[str] = None,
    fragment_req_id: Optional[str] = None,
    fragment_payload: Optional[str] = None,
    fragment_tx_hash: Optional[str] = None,
    fulfillment_error: Optional[str] = None,
) -> Optional[Order]:
    order = await session.get(Order, order_id)
    if not order:
        return None
    order.fulfillment_status = fulfillment_status
    if status is not None:
        norm = OrderStatus.COMPLETED if status == "done" else (OrderStatus.CANCELLED if status == "cancel" else status)
        order.status = norm
        if norm == OrderStatus.COMPLETED:
            order.completed_at = utc_now()
    if fragment_req_id is not None:
        order.fragment_req_id = fragment_req_id
    if fragment_payload is not None:
        order.fragment_payload = fragment_payload
    if fragment_tx_hash is not None:
        order.fragment_tx_hash = fragment_tx_hash
    if fulfillment_error is not None:
        order.fulfillment_error = fulfillment_error
    await session.commit()
    return order


# ================= PAYMENT SETTINGS ================= #


async def get_payment_settings(session: AsyncSession) -> PaymentSetting:
    setting = await session.get(PaymentSetting, 1)
    if not setting:
        setting = PaymentSetting(id=1)
        session.add(setting)
        await session.commit()
        await session.refresh(setting)
    return setting


async def update_payment_settings(
    session: AsyncSession,
    click_active: Optional[bool] = None,
    payme_active: Optional[bool] = None,
    card_active: Optional[bool] = None,
    card_number: Optional[str] = None,
    card_holder: Optional[str] = None,
    bank_name: Optional[str] = None,
) -> PaymentSetting:
    setting = await get_payment_settings(session)
    if click_active is not None:
        setting.click_active = click_active
    if payme_active is not None:
        setting.payme_active = payme_active
    if card_active is not None:
        setting.card_active = card_active
    if card_number is not None:
        setting.card_number = card_number.strip()
    if card_holder is not None:
        setting.card_holder = card_holder.strip().upper()
    if bank_name is not None:
        setting.bank_name = bank_name.strip()
    await session.commit()
    await session.refresh(setting)
    return setting


# ================= REFERRAL SETTINGS ================= #


async def get_referral_settings(session: AsyncSession) -> ReferralSetting:
    ref = await session.get(ReferralSetting, 1)
    if not ref:
        ref = ReferralSetting(
            id=1,
            bonus_percent=Decimal("5.00"),
            min_purchase_uzs=Decimal("20000.00"),
            auto_reward=True,
            require_purchase=True,
        )
        session.add(ref)
        await session.commit()
        await session.refresh(ref)
    return ref


# ================= CUSTOM SERVICES ================= #


async def list_custom_services(session: AsyncSession, active_only: bool = False) -> List[CustomService]:
    query = select(CustomService).order_by(CustomService.id)
    if active_only:
        query = query.where(CustomService.is_active == True)
    res = await session.execute(query)
    return list(res.scalars().all())


async def get_custom_service(session: AsyncSession, service_id: int) -> Optional[CustomService]:
    return await session.get(CustomService, service_id)


async def create_custom_service(
    session: AsyncSession,
    name: str,
    price_uzs: float,
    cost_uzs: float = 0.0,
    category: str = "Xizmatlar",
    icon: str = "⚡",
    description: str = "",
    is_active: bool = True,
) -> CustomService:
    service = CustomService(
        name=name.strip(),
        price_uzs=Decimal(str(price_uzs)),
        cost_uzs=Decimal(str(cost_uzs)),
        category=category.strip() if category else "Xizmatlar",
        icon=icon.strip() if icon else "⚡",
        description=description.strip() if description else "",
        is_active=is_active,
        created_at=utc_now(),
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


async def update_custom_service(
    session: AsyncSession,
    service_id: int,
    name: Optional[str] = None,
    price_uzs: Optional[float] = None,
    cost_uzs: Optional[float] = None,
    category: Optional[str] = None,
    icon: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[CustomService]:
    service = await session.get(CustomService, service_id)
    if not service:
        return None
    if name is not None:
        service.name = name.strip()
    if price_uzs is not None:
        service.price_uzs = Decimal(str(price_uzs))
    if cost_uzs is not None:
        service.cost_uzs = Decimal(str(cost_uzs))
    if category is not None:
        service.category = category.strip()
    if icon is not None:
        service.icon = icon.strip()
    if description is not None:
        service.description = description.strip()
    if is_active is not None:
        service.is_active = is_active
    await session.commit()
    await session.refresh(service)
    return service


async def delete_custom_service(session: AsyncSession, service_id: int) -> bool:
    service = await session.get(CustomService, service_id)
    if not service:
        return False
    await session.delete(service)
    await session.commit()
    return True


# ================= PAYMENT CARDS ================= #


async def list_payment_cards(session: AsyncSession, active_only: bool = False) -> List[PaymentCard]:
    query = select(PaymentCard).order_by(PaymentCard.id)
    if active_only:
        query = query.where(PaymentCard.is_active == True)
    res = await session.execute(query)
    return list(res.scalars().all())


async def list_active_payment_cards(session: AsyncSession) -> List[PaymentCard]:
    cards = await list_payment_cards(session, active_only=True)
    if not cards:
        p = await get_payment_settings(session)
        if p and p.card_active and p.card_number:
            return [
                PaymentCard(
                    id=0,
                    card_number=p.card_number,
                    card_holder=p.card_holder,
                    bank_name=p.bank_name,
                    card_type="UZCARD"
                    if p.card_number.startswith("8600")
                    else ("HUMO" if p.card_number.startswith("9860") else "VISA"),
                    is_active=True,
                )
            ]
    return cards


async def get_payment_card(session: AsyncSession, card_id: int) -> Optional[PaymentCard]:
    return await session.get(PaymentCard, card_id)


async def create_payment_card(
    session: AsyncSession,
    card_number: str,
    card_holder: str,
    bank_name: str,
    card_type: str = "UZCARD",
    is_active: bool = True,
) -> PaymentCard:
    card = PaymentCard(
        card_number=card_number.strip(),
        card_holder=card_holder.strip().upper(),
        bank_name=bank_name.strip(),
        card_type=card_type.strip().upper(),
        is_active=is_active,
        created_at=utc_now(),
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card


async def update_payment_card(
    session: AsyncSession,
    card_id: int,
    card_number: Optional[str] = None,
    card_holder: Optional[str] = None,
    bank_name: Optional[str] = None,
    card_type: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[PaymentCard]:
    card = await session.get(PaymentCard, card_id)
    if not card:
        return None
    if card_number is not None:
        card.card_number = card_number.strip()
    if card_holder is not None:
        card.card_holder = card_holder.strip().upper()
    if bank_name is not None:
        card.bank_name = bank_name.strip()
    if card_type is not None:
        card.card_type = card_type.strip().upper()
    if is_active is not None:
        card.is_active = is_active
    await session.commit()
    await session.refresh(card)
    return card


async def delete_payment_card(session: AsyncSession, card_id: int) -> bool:
    card = await session.get(PaymentCard, card_id)
    if not card:
        return False
    await session.delete(card)
    await session.commit()
    return True
